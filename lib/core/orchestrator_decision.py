"""Решение уровня команд: commands.json → Laya/legacy (миксин оркестратора).

Вынесено из lib/core/orchestrator.py, чтобы держать файлы ≤ 200 строк.
"""


class OrchestratorDecisionMixin:
    """Шаг 1..3: commands.json, алиасы, decision-слой Laya, legacy fallback."""

    def _execute_decision(self, cmd_id: str, text: str) -> bool:
        """Запускает команду алиаса/Laya, подставляя ядро фразы в {{text}}.

        Laya и алиасы возвращают только id команды; команды со свободным
        текстом (taskstart, calendar-reminder) иначе запускаются с пустым
        аргументом. Для них слова фразы без триггеров уходят как settings.
        """
        settings = ()
        if self._matcher.needs_text(cmd_id):
            settings = self._decision_text(cmd_id, text)
        if settings:
            return self._matcher.execute_by_id(cmd_id, settings)
        return self._matcher.execute_by_id(cmd_id)

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
        # 1. Команды commands.json — концепция «трёх строк».
        self._window.append(text)
        cmd_id, settings, wait = self._matcher.find_command(
            list(self._window))
        if wait:
            # Ключ есть, команды вокруг него нет — ждём следующую строку.
            self._output.print_info(
                "[Command] commands.json: ключ есть, команды нет — "
                "ждём следующую строку")
            return
        blocked: list[tuple[str, list[str]]] = []
        if cmd_id is not None:
            missing = self._matcher.missing_requires(cmd_id)
            if not missing:
                self._output.print_info(
                    f"[Command] Распознана команда: {cmd_id}"
                    + (f" (настройки: {', '.join(settings)})"
                       if settings else ""))
                self._execute_with_settings(cmd_id, settings)
                self._window.clear()
                return
            blocked = [(cmd_id, missing)]
            self._window.clear()
            self._output.print_info(
                f"[Command] Команда {cmd_id} найдена, но заблокирована: "
                f"нет статуса: {', '.join(missing)}")
        # Команды из commands.json нет (или она заблокирована) — дальше
        # старые уровни: алиасы/decision/opencode.
        if not self._matcher.has_trigger(text):
            return
        literal_id = cmd_id  # найденная (даже заблокированная) команда
        if cmd_id is None:
            self._output.print_info(
                "[Command] В commands.json команда не найдена")
        # 1.5. Известное коверканье из базы алиасов — без вызова LLM.
        if cmd_id is None and self._aliases is not None:
            core = self._matcher.core_phrase(text)
            alias_id = self._aliases.resolve(core)
            if alias_id is not None:
                missing = self._matcher.missing_requires(alias_id)
                if not missing:
                    self._output.print_info(
                        f"[Alias] Распознана команда: {alias_id}")
                    self._aliases.bump(core)
                    self._execute_decision(alias_id, text)
                    return
                blocked = [(alias_id, missing)]
            else:
                self._output.print_debug(
                    "[Alias] В алиасах совпадений нет")
        # 2. Decision-слой: дисижн-модель Laya (commands.json не совпало).
        if self._decision is not None:
            self._output.print_info("[Decision] Обращение к Лайе...")
            detected = self._decision.detect(text)
            if detected is None:
                # Заглушка OmniRouter (auto/fast): сам запрос пока не делаем.
                self._output.print_info(
                    "[Decision] Лайя: команда не распознана — запрос ушёл бы "
                    "в OmniRouter (auto/fast), пока пропускаем"
                )
                return
            resolved, confidence, elapsed = detected
            self._output.print_info(
                f"[Decision] Лайя: команда распознана «{resolved}» "
                f"(c={confidence:.2f} t={elapsed:.3f})")
            if self._execute_decision(resolved, text):
                self._output.print_text(resolved)
                self._remember_candidate(text, resolved, literal_id)
                return
            missing = self._matcher.missing_requires(resolved)
            if missing:
                self._report_blocked(resolved, missing)
                return
            self._output.print_error(
                f"[Decision] Команда «{resolved}» не найдена или не выполнена")
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
            f"[OpenCode Decision] No literal, no alias, no intent match. "
            f"Sending to opencode-cli. Text: {text}"
        )
        self._output.print_info("... отправка запроса в opencode-cli (фон)")
        self._enqueue_opencode(text)
