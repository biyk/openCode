"""Решение уровня команд: commands.json → Laya/legacy (миксин оркестратора).

Вынесено из lib/core/orchestrator.py, чтобы держать файлы ≤ 200 строк.
"""

from typing import Optional


class OrchestratorDecisionMixin:
    """Шаг 1..3: commands.json, алиасы, decision-слой Laya, legacy fallback."""

    def _execute_decision(self, cmd_id: str, text: str,
                          forced_text: Optional[str] = None) -> bool:
        """Запускает команду знания/Laya, подставляя ядро фразы в {{text}}.

        Laya и база знаний возвращают только id команды; команды со свободным
        текстом (task-add, calendar-reminder) иначе запускаются с пустым
        аргументом. Если на доске для confirmed-записи выбран ключ (event),
        он идёт в {{text}} как есть — рантайм не перерезает фразу заново.
        """
        settings = ()
        if self._matcher.needs_text(cmd_id):
            if forced_text:
                settings = (forced_text,)
            else:
                settings = self._decision_text(cmd_id, text)
        if settings:
            ok = self._matcher.execute_by_id(cmd_id, settings)
        else:
            ok = self._matcher.execute_by_id(cmd_id)
        if ok:
            self._chat_done(cmd_id)   # чату видно результат (голос — озвучкой)
            self._ack(cmd_id)         # голосу — короткое «Хорошо» где нужно
            self._maybe_flavor(cmd_id, text)
        return ok

    def _decision_text(self, cmd_id: str, text: str) -> tuple[str, ...]:
        """Слова фразы для {{text}}: ядро без триггеров и ведущих командных слов.

        «поставь дальше приготовить гречку» для task-add → «дальше
        приготовить гречку»: срезается только ведущие слова из match-
        шаблонов команды, хвост фразы не трогается.
        """
        tokens = self._matcher.core_phrase(text).split()
        words: set[str] = set()
        for tpl in self._matcher.match_config().get(cmd_id, []):
            words.update(tpl.lower().split())
        while tokens and tokens[0] in words:
            tokens = tokens[1:]
        return tuple(tokens)

    def _process_commands_level(self, text: str) -> None:
        """Обрабатывает цепочку: commands.json → Laya/legacy → opencode."""
        # 1. Команды commands.json — триггер и команда в одной строке.
        cmd_id, settings = self._matcher.find_command(text)
        blocked: list[tuple[str, list[str]]] = []
        if cmd_id is not None:
            missing = self._matcher.missing_requires(cmd_id)
            if not missing:
                self._output.print_info(
                    f"[Command] Распознана команда: {cmd_id}"
                    + (f" (настройки: {', '.join(settings)})"
                       if settings else ""))
                if self._execute_with_settings(cmd_id, settings):
                    self._chat_done(cmd_id)
                    self._ack(cmd_id)
                    self._maybe_flavor(cmd_id, text)
                else:
                    self._chat_reply(f"Команда «{cmd_id}» не выполнена")
                return
            blocked = [(cmd_id, missing)]
            self._output.print_info(
                f"[Command] Команда {cmd_id} найдена, но заблокирована: "
                f"нет статуса: {', '.join(missing)}")
        # Команды из commands.json нет (или она заблокирована) — дальше
        # уровни: decision/legacy-opencode.
        if not self._matcher.has_trigger(text):
            return
        literal_id = cmd_id  # найденная (даже заблокированная) команда
        if cmd_id is None:
            self._output.print_info(
                "[Command] В commands.json команда не найдена")
        # 1.6. База знаний: подтверждённые досмотром команда/мероприятие —
        # без вызова LLM и без нечёткого матчинга по календарю.
        if cmd_id is None and self._knowledge is not None:
            kcore = self._matcher.core_phrase(text)
            kid, ktext = self._knowledge.resolve_text(kcore)
            if kid is not None:
                missing = self._matcher.missing_requires(kid)
                if not missing:
                    self._output.print_info(
                        f"[Knowledge] Распознана команда: {kid}")
                    self._knowledge.bump(kcore)
                    self._execute_decision(kid, text, ktext)
                    return
                blocked = [(kid, missing)]
            else:
                hit = self._knowledge.resolve_event(kcore)
                if hit is not None:
                    self._knowledge.bump(kcore)
                    self._execute_event_action(hit[0], hit[1])
                    return
        # 1.7. Само-отчёт («я почистил зубы», «закончил зарядку») — не просьба
        # к ассистенту, а старт/финиш сегодняшнего мероприятия. Пробуем
        # привязать к невыполненному событию ДО Лайи: иначе Лайя ложно тянет
        # бытовое прошедшее действие к «wakefix» (утренний ритуал ≡ проснулся).
        if self._is_self_report(text) and self._try_event_match(text):
            return
        # 2. Decision-слой: дисижн-модель Laya (commands.json не совпало).
        if self._decision is not None:
            self._output.print_info("[Decision] Обращение к Лайе...")
            detected = self._decision.detect(text)
            if detected is None:
                # Лайя не распознала команду — пробуем привязать фразу
                # к невыполненному мероприятию сегодня (start/complete).
                if self._try_event_match(text):
                    return
                # Затем LLM-детект команды (OmniRouter/LM Studio) по примеру
                # распознавания на доске; нашёл — исполнит и ляжет в laya.
                if self._llm is not None and self._run_llm_fallback(text):
                    return
                self._record_undefined(text)
                self._output.print_info(
                    "[Decision] Лайя и LLM: команда не распознана — "
                    "фраза в undefined, запрос в opencode не идёт"
                )
                self._chat_not_recognized()
                return
            resolved, confidence, elapsed = detected
            self._output.print_info(
                f"[Decision] Лайя: команда распознана «{resolved}» "
                f"(c={confidence:.2f} t={elapsed:.3f})")
            # Пишем в корзину laya сразу: ложные срабатывания (в т.ч. те,
            # что упадут на requires) тоже должны попасть на досмотр.
            self._remember_candidate(text, resolved, literal_id)
            if self._execute_decision(resolved, text):
                self._output.print_text(resolved)
                return
            missing = self._matcher.missing_requires(resolved)
            if missing:
                self._report_blocked(resolved, missing)
                return
            self._output.print_error(
                f"[Decision] Команда «{resolved}» не найдена или не выполнена")
            self._chat_reply(
                f"Команда «{resolved}» не найдена или не выполнена")
            return
        # 3. Legacy-путь (decision не настроен): mini-LLM intent, затем
        # фолбэк в console opencode.
        if self._intent is not None:
            detected = self._intent.detect(text, self._llm_context(blocked))
            if detected is not None:
                self._output.print_info(
                    f"[Mini] Распознана команда «{detected}»"
                )
                if self._matcher.execute_by_id(detected):
                    self._output.print_text(detected)
                    self._chat_done(detected)
                    self._ack(detected)
                    self._maybe_flavor(detected, text)
                    self._remember_candidate(text, detected, literal_id)
                    return
                missing = self._matcher.missing_requires(detected)
                if missing:
                    self._report_blocked(detected, missing)
                    return
                self._output.print_error(
                    f"[Mini] Команда «{detected}» не найдена"
                )
                return
        self._output.print_debug(
            f"[OpenCode Decision] No literal, no knowledge, no intent match. "
            f"Sending to opencode-cli. Text: {text}"
        )
        self._record_undefined(text)
        self._output.print_info("... отправка запроса в opencode-cli (фон)")
        self._enqueue_opencode(text)
