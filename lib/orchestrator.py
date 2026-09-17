"""Оркестратор обработки голосового ввода (детерминированное ядро).

Решает, на каком из трёх уровней обрабатывать распознанный текст:
1. commands.json (дословное совпадение + алиасы),
2. mini-LLM (интеллектуальный классификатор команд),
3. console opencode (opencode-cli в cli/, использует скиллы).

Большой чат LLM убран: фолбэк уходит в консольный opencode, который сам
выполняет команду и озвучивает результат через скилл speak-answer.
"""

import queue
import threading
import time
from typing import Any, Callable, Optional

from lib.aliases import AliasStore
from lib.commands import CommandMatcher
from lib.output import TranscriptionOutput
from lib.opencode_cli import OpenCodeCliRunner


class Orchestrator:
    """Детерминированный слой принятия решений для распознанного текста."""

    def __init__(
        self,
        matcher: CommandMatcher,
        output: TranscriptionOutput,
        tts: Any,
        stop_words: frozenset[str] = frozenset(
            ("стоп", "останови", "stop", "хватит", "прекрати")
        ),
        suppress_after: float = 0.5,
        clear_speech_buffer: Optional[Callable[[], None]] = None,
        intent: Any = None,
        aliases: Optional[AliasStore] = None,
        opencode: Optional[OpenCodeCliRunner] = None,
    ) -> None:
        self._matcher = matcher
        self._output = output
        self._tts = tts
        self._stop_words = stop_words
        self._suppress_after = suppress_after
        self._clear_speech_buffer = clear_speech_buffer or (lambda: None)
        self._intent = intent or None
        self._aliases = aliases or None
        self._opencode = opencode or None
        self._speaking = False
        self._abort_playback = threading.Event()
        self._suppress_until = 0.0
        self._last_resolution: Optional[tuple[str, str]] = None
        self._opencode_queue: queue.Queue[Optional[str]] = queue.Queue()
        self._opencode_worker: Optional[threading.Thread] = None
        self._opencode_active = False

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
        if self._opencode_active and self.maybe_abort(text):
            # Пока opencode думает, стоп-слово только отменяет ожидаемый ответ
            return
        if not self._matcher.has_trigger(text):
            self._output.print_text(text)
            return
        # Сначала выводим распознанный текст (с триггером) в консоль и лог
        self._output.print_text(text)
        # 0. Мета-команды обучения алиасов («запомни»/«забудь»).
        if self._aliases is not None and self._handle_memory_command(text):
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
        # 2. Не дословно — мини-LLM классификатор команд.
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

    def _enqueue_opencode(self, text: str) -> None:
        """Ставит текст в фоновую очередь console opencode."""
        if self._opencode is None:
            self._output.print_error("[OpenCode] Раннер не настроен")
            return
        self._opencode_queue.put(text)
        self._ensure_opencode_worker()

    def _drain_opencode_queue(self) -> None:
        """Выбрасывает накопленные, но ещё не обработанные запросы opencode."""
        discarded = 0
        while True:
            try:
                self._opencode_queue.get_nowait()
                discarded += 1
            except Exception:
                break
        if discarded:
            self._output.print_debug(
                f"[OpenCode] Отброшено запросов: {discarded}")

    def _ensure_opencode_worker(self) -> None:
        """Запускает воркер, если он ещё не создан."""
        if self._opencode_worker is not None:
            return
        self._opencode_worker = threading.Thread(
            target=self._opencode_worker_loop, daemon=True)
        self._opencode_worker.start()

    def _opencode_worker_loop(self) -> None:
        """Фоновый воркер: обрабатывает запросы из очереди."""
        while True:
            text = self._opencode_queue.get()
            started = time.monotonic()
            try:
                self._opencode_active = True
                self._output.print_info(
                    f"[OpenCode] Выполняю в фоне: «{text[:60]}...»"
                    if len(text) > 60 else f"[OpenCode] Выполняю: «{text}»"
                )
                if self._abort_playback.is_set():
                    self._output.print_debug(
                        "[OpenCode] Запрос отменён (стоп)")
                    continue
                answer = self._opencode.run(text, abort_event=self._abort_playback)
                if self._abort_playback.is_set():
                    self._output.print_debug(
                        "[OpenCode] Ответ отменён (стоп)")
                    continue
                if not answer:
                    self._output.print_error(
                        "[OpenCode] Пустой ответ агента (возможно, таймаут "
                        "или opencode не смог выполнить команду)")
                    continue
                elapsed = time.monotonic() - started
                # Результат — в консоль (только читаемый итог), подробности — в лог
                self._output.print_info(
                    f"[OpenCode] Итог ({elapsed:.0f}с): {answer}")
                self._output.print_debug(
                    f"[OpenCode] Ответ (сводка): {answer}")
            except Exception as e:
                self._output.print_error(
                    f"[OpenCode] Ошибка фонового запроса: {e}")
            finally:
                self._opencode_active = False
                self._opencode_queue.task_done()

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
        """Прерывает озвучку или ожидающий ответ opencode, если есть стоп-слово.

        Возвращает True, если процесс был прерван. Используется для
        финальных и частичных результатов распознавания.
        """
        if not self._speaking and not self._opencode_active:
            return False
        tokens = text.lower().split()
        if not any(token in self._stop_words for token in tokens):
            return False
        self._abort_playback.set()
        if self._speaking:
            self._output.print_info("[TTS] Озвучка прервана")
        else:
            self._output.print_info("[OpenCode] Ожидаемый ответ отменён")
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
        """Прерывает активное воспроизведение TTS и очищает очередь opencode."""
        self._abort_playback.set()
        self._drain_opencode_queue()
