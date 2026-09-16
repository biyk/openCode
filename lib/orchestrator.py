"""Оркестратор обработки голосового ввода (детерминированное ядро).

Решает, на каком уровне обрабатывать распознанный текст: стоп-слово во время
озвучки, готовая команда, скилл или запрос к LLM. Сюда же подключаются будущие слои
(мини-LLM, большая LLM, модель-контролёр), не затрагивая ядро
распознавания в main.py.
"""

import queue
import threading
import time
from typing import Any, Callable, Optional

from lib.aliases import AliasStore
from lib.commands import CommandMatcher
from lib.output import TranscriptionOutput
from lib.plans import PlansHandler
from lib.reminders import ReminderHandler
from lib.skills import SkillRegistry


class Orchestrator:
    """Детерминированный слой принятия решений для распознанного текста."""

    def __init__(
        self,
        matcher: CommandMatcher,
        output: TranscriptionOutput,
        llm: Any,
        tts: Any,
        stop_words: frozenset[str] = frozenset(
            ("стоп", "останови", "stop", "хватит", "прекрати")
        ),
        suppress_after: float = 0.5,
        clear_speech_buffer: Optional[Callable[[], None]] = None,
        intent: Any = None,
        skills: Optional[SkillRegistry] = None,
        aliases: Optional[AliasStore] = None,
        reminders: Optional[ReminderHandler] = None,
        plans: Optional[PlansHandler] = None,
    ) -> None:
        self._matcher = matcher
        self._output = output
        self._llm = llm
        self._tts = tts
        self._stop_words = stop_words
        self._suppress_after = suppress_after
        self._clear_speech_buffer = clear_speech_buffer or (lambda: None)
        self._intent = intent or None
        self._skills = skills or None
        self._aliases = aliases or None
        self._reminders = reminders or None
        self._plans = plans or None
        self._speaking = False
        self._abort_playback = threading.Event()
        self._suppress_until = 0.0
        self._last_resolution: Optional[tuple[str, str]] = None
        self._llm_queue: queue.Queue[Optional[str]] = queue.Queue()
        self._llm_worker: Optional[threading.Thread] = None
        self._llm_active = False

    @property
    def speaking(self) -> bool:
        """Идёт ли сейчас озвучка TTS."""
        return self._speaking

    @property
    def abort_playback(self) -> threading.Event:
        """Событие прерывания синтеза/воспроизведения TTS."""
        return self._abort_playback

    @property
    def suppress_until(self) -> float:
        """Момент (time.monotonic) окончания окна эхо-затишья."""
        return self._suppress_until

    def process_text(self, text: str) -> None:
        """Обрабатывает текст: стоп-слово, команда или запрос к LLM."""
        if time.monotonic() < self._suppress_until:
            return
        if self._speaking:
            self.maybe_abort(text)
            return
        if self._llm_active and self.maybe_abort(text):
            # Пока LLM думает, стоп-слово только отменяет ожидаемый ответ
            return
        if not self._matcher.has_trigger(text):
            self._output.print_text(text)
            return
        # Сначала выводим распознанный текст (с триггером) в консоль и лог
        self._output.print_text(text)
        # 0. Мета-команды обучения алиасов («запомни»/«забудь»).
        if self._aliases is not None and self._handle_memory_command(text):
            return
        # 0.5. Напоминания («напомни через 3 часа ...») — в Google Calendar.
        if self._reminders is not None and self._handle_reminder(text):
            return
        # 0.7. Планы на день («что у меня сейчас по планам») — из календаря.
        if self._plans is not None and self._handle_plans(text):
            return
        # 1. Дословное совпадение — запускаем сразу.
        literal_id = self._matcher.find_literal_id(text)
        blocked: list[tuple[str, list[str]]] = []
        if literal_id is not None:
            missing = self._matcher.missing_requires(literal_id)
            if not missing:
                self._output.print_info(
                    f"[Command] Распознана команда: {literal_id}")
                self._matcher.execute_by_id(literal_id)
                return
            blocked = [(literal_id, missing)]
        # 1.5. Известное коверканье из базы алиасов — без вызова LLM.
        elif self._aliases is not None:
            core = self._matcher.core_phrase(text)
            alias_id = self._aliases.resolve(core)
            if alias_id is not None:
                missing = self._matcher.missing_requires(alias_id)
                if not missing:
                    self._output.print_info(
                        f"[Alias] Распознана команда: {alias_id}")
                    self._aliases.bump(core)
                    self._matcher.execute_by_id(alias_id)
                    return
                blocked = [(alias_id, missing)]
        # 2. Не дословно — пусть разбирается LLM: отдаём ей триггеры,
        #    команды, статусы и заблокированных кандидатов.
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
        # Проверка скиллов (после intent, до LLM)
        if self._skills is not None:
            skill_name = self._skills.match(text)
            if skill_name is not None:
                self._output.print_info(f"[Skill] Распознан скилл: {skill_name}")
                if self._skills.execute(skill_name):
                    self._output.print_text(f"Скилл выполнен: {skill_name}")
                    return
                self._output.print_error(f"[Skill] Ошибка исполнения: {skill_name}")
                return
        self._output.print_debug(
            f"[LLM Decision] Trigger found, no command match, no intent match, no skill match. "
            f"Sending to LLM. Text: {text}"
        )
        self._output.print_info("... отправка запроса LLM (фон)")
        self._enqueue_llm(text)

    def _enqueue_llm(self, text: str) -> None:
        """Ставит текст в фоновую очередь LLM."""
        self._llm_queue.put(text)
        self._ensure_llm_worker()

    def _drain_llm_queue(self) -> None:
        """Выбрасывает накопленные, но ещё не обработанные запросы LLM."""
        discarded = 0
        while True:
            try:
                self._llm_queue.get_nowait()
                discarded += 1
            except Exception:
                break
        if discarded:
            self._output.print_debug(f"[LLM] Отброшено запросов: {discarded}")

    def _ensure_llm_worker(self) -> None:
        """Запускает воркер, если он ещё не создан."""
        if self._llm_worker is not None:
            return
        self._llm_worker = threading.Thread(
            target=self._llm_worker_loop, daemon=True)
        self._llm_worker.start()

    def _llm_worker_loop(self) -> None:
        """Фоновый воркер: обрабатывает запросы из очереди."""
        while True:
            text = self._llm_queue.get()
            try:
                self._llm_active = True
                if self._abort_playback.is_set():
                    self._output.print_debug("[LLM] Запрос отменён (стоп)")
                    continue
                answer = self._llm.ask(text)
                if self._abort_playback.is_set():
                    self._output.print_debug("[LLM] Ответ отменён (стоп)")
                    continue
                if not answer:
                    self._output.print_error("[LLM] Ошибка ответа")
                    self._output.print_text(text)
                    continue
                self._output.print_debug(f"[LLM] Ответ: {answer}")
                # Ждём, пока предыдущая озвучка не закончится (одна голосовая
                # линия), чтобы ответы не накладывались друг на друга.
                while self._speaking and not self._abort_playback.is_set():
                    time.sleep(0.05)
                if self._abort_playback.is_set():
                    self._output.print_debug("[LLM] Ответ отменён (стоп)")
                    continue
                self._speaking = True
                self._abort_playback.clear()
                self._speak_async(answer)
            except Exception as e:
                self._output.print_error(f"[LLM] Ошибка фонового запроса: {e}")
            finally:
                self._llm_active = False
                self._llm_queue.task_done()

    def _remember_candidate(self, text: str, cmd_id: str,
                            literal_id: Optional[str]) -> None:
        """Сохраняет авто-кандидата в pending (только для недословных).

        Дословные фразы учить не нужно — они уже шаблоны. Запоминает
        последнее разрешение для команды «запомни» без аргументов.
        """
        if self._aliases is None:
            return
        core = self._matcher.core_phrase(text)
        self._last_resolution = (core, cmd_id)
        if literal_id is None and core:
            self._aliases.add(core, cmd_id, confirmed=False)

    def _known_ids(self) -> set[str]:
        """Все известные id команд (включая sequences)."""
        ids = set(self._matcher.match_config())
        try:
            ids.update(self._matcher.sequences())
        except Exception:
            pass
        return ids

    def _say(self, message: str) -> None:
        """Короткое голосовое подтверждение."""
        self._output.print_info(f"[Memory] {message}")
        self._speaking = True
        self._abort_playback.clear()
        self._speak_async(message)

    def _handle_memory_command(self, text: str) -> bool:
        """Обрабатывает «запомни»/«забудь». Возвращает True, если это они."""
        core = self._matcher.core_phrase(text)
        if not core:
            return False
        if core == "запомни" or core.startswith("запомни "):
            self._remember_voice(core)
            return True
        if core == "забудь" or core.startswith("забудь "):
            self._forget_voice(core)
            return True
        return False

    def _remember_voice(self, core: str) -> None:
        """Голосовое обучение: «запомни» / «запомни X это Y»."""
        assert self._aliases is not None
        rest = core[len("запомни"):].strip()
        if not rest:
            # Без аргументов — подтвердить последнее разрешение.
            if self._last_resolution is None:
                self._say("Нечего запоминать")
                return
            phrase, cmd_id = self._last_resolution
            if self._aliases.resolve(phrase) == cmd_id:
                self._say("Уже запомнила")
                return
            confirmed = self._aliases.confirm(phrase)
            if confirmed is not None:
                self._say(f"Запомнила: {phrase} это {confirmed}")
                return
            self._aliases.add(phrase, cmd_id, confirmed=True)
            self._say(f"Запомнила: {phrase} это {cmd_id}")
            return
        if " это " in rest:
            phrase, _, cmd_id = rest.partition(" это ")
            phrase, cmd_id = phrase.strip(), cmd_id.strip()
            if not phrase or not cmd_id:
                self._say("Не поняла, что запомнить")
                return
            if cmd_id not in self._known_ids():
                self._say(f"Не знаю команду {cmd_id}")
                return
            self._aliases.add(phrase, cmd_id, confirmed=True)
            self._say(f"Запомнила: {phrase} это {cmd_id}")
            return
        self._say("Скажи: запомни, что именно и какая команда")

    def _forget_voice(self, core: str) -> None:
        """Голосовое удаление: «забудь X»."""
        assert self._aliases is not None
        rest = core[len("забудь"):].strip()
        if not rest:
            self._say("Скажи, что забыть")
            return
        if self._aliases.forget(rest):
            self._say(f"Забыла: {rest}")
        else:
            self._say("Такого не помню")

    def _handle_reminder(self, text: str) -> bool:
        """Обрабатывает напоминания. Возвращает True, если текст — напоминание."""
        assert self._reminders is not None
        if not self._reminders.is_reminder(text):
            return False
        self._output.print_info("[Reminder] Распознано напоминание")
        spec = self._reminders.create(text)
        if spec is None:
            self._say("Не поняла, что напомнить")
            return True
        event_id = self._reminders.add_event(spec)
        if event_id is None:
            self._output.print_error("[Google] Ошибка создания напоминания")
            if not self._reminders.auth_ready():
                self._say("Для напоминаний нужна авторизация Google. "
                          "Скажи \"авторизация\".")
            else:
                self._say("Не получилось создать напоминание — проверь "
                          "авторизацию Google")
            return True
        when_str = spec.when.strftime("%d.%m %H:%M")
        message = f"Напомню {when_str}: {spec.text}"
        self._output.print_info(f"[Google] Создано: {message} (event {event_id})")
        self._say(message)
        return True

    def _handle_plans(self, text: str) -> bool:
        """Обрабатывает запрос планов. Возвращает True, если это он."""
        assert self._plans is not None
        if not self._plans.is_plans_query(text):
            return False
        self._output.print_info("[Plans] Запрос планов распознан")
        if not self._plans.auth_ready():
            self._say("Для планов нужна авторизация Google. "
                      "Скажи \"авторизация\".")
            return True
        task = self._plans.current_task()
        if task is None:
            self._say("По планам сейчас ничего нет")
            return True
        summary = task.get("summary") or "задача"
        start = task.get("start")
        if start is not None:
            time_str = start.strftime("%H:%M")
            message = f"Сейчас по планам: {summary} в {time_str}"
        else:
            message = f"Сейчас по планам: {summary}"
        self._output.print_info(f"[Plans] Актуальная задача: {message}")
        self._say(message)
        return True

    def _llm_context(self,
                     blocked: list[tuple[str, list[str]]]) -> dict:
        """Контекст для LLM-классификатора: триггеры, команды, статусы."""
        return {
            "triggers": list(self._matcher.triggers),
            "statuses": self._matcher.status_snapshot(),
            "requires": self._matcher.requires_map(),
            "blocked": [(bid, list(missing)) for bid, missing in blocked],
        }

    def _report_blocked(self, cmd_id: str, missing: list[str]) -> None:
        """Сообщает, каких статусов не хватает (консоль + голос).

        Вместо молчаливого ухода в LLM пользователь слышит,
        что нужно сделать (например, «Включи VPN вручную»).
        """
        names = ", ".join(missing)
        self._output.print_error(f"[Blocked] «{cmd_id}»: нет статуса: {names}")
        message = ". ".join(self._matcher.need_message(n) for n in missing)
        self._speaking = True
        self._abort_playback.clear()
        self._speak_async(message)

    def maybe_abort(self, text: str) -> bool:
        """Прерывает озвучку или ожидающий ответ LLM, если есть стоп-слово.

        Возвращает True, если процесс был прерван. Используется для
        финальных и частичных результатов распознавания.
        """
        if not self._speaking and not self._llm_active:
            return False
        tokens = text.lower().split()
        if not any(token in self._stop_words for token in tokens):
            return False
        self._abort_playback.set()
        if self._speaking:
            self._output.print_info("[TTS] Озвучка прервана")
        else:
            self._output.print_info("[LLM] Ожидаемый ответ отменён")
        return True

    def _speak_async(self, answer: str) -> None:
        """Запускает озвучку в фоне, оставляя цикл распознавания активным."""
        def _play() -> None:
            try:
                self._tts.speak_and_play(answer, abort_event=self._abort_playback)
            except Exception as e:
                self._output.print_error(f"Ошибка озвучки: {e}")
            finally:
                self._on_speaking_finished()

        threading.Thread(target=_play, daemon=True).start()

    def _on_speaking_finished(self) -> None:
        """Сбрасывает флаг озвучки и ставит окно эхо-затишья."""
        self._speaking = False
        self._suppress_until = time.monotonic() + self._suppress_after
        self._clear_speech_buffer()

    def stop(self) -> None:
        """Прерывает активное воспроизведение TTS и очищает очередь LLM."""
        self._abort_playback.set()
        self._drain_llm_queue()
