"""Оркестратор обработки голосового ввода (детерминированное ядро).

Решает, на каком уровне обрабатывать распознанный текст: стоп-слово во время
озвучки, готовая команда, скилл или запрос к LLM. Сюда же подключаются будущие слои
(мини-LLM, большая LLM, модель-контролёр), не затрагивая ядро
распознавания в main.py.
"""

import threading
import time
from typing import Any, Callable, Optional

from lib.commands import CommandMatcher
from lib.output import TranscriptionOutput
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
        self._speaking = False
        self._abort_playback = threading.Event()
        self._suppress_until = 0.0

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
        if not self._matcher.has_trigger(text):
            self._output.print_text(text)
            return
        # Сначала выводим распознанный текст (с триггером) в консоль и лог
        self._output.print_text(text)
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
        self._output.print_info("... отправка запроса LLM")
        answer = self._llm.ask(text)
        if answer:
            self._output.print_debug(f"[LLM] Ответ: {answer}")
            self._speaking = True
            self._abort_playback.clear()
            self._speak_async(answer)
        else:
            self._output.print_error("[LLM] Ошибка ответа")
            self._output.print_text(text)

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
        """Прерывает озвучку, если в тексте есть стоп-слово (целое слово).

        Возвращает True, если озвучка была прервана. Используется для
        финальных и частичных результатов распознавания.
        """
        if not self._speaking:
            return False
        tokens = text.lower().split()
        if not any(token in self._stop_words for token in tokens):
            return False
        self._abort_playback.set()
        self._output.print_info("[TTS] Озвучка прервана")
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
        """Прерывает активное воспроизведение TTS."""
        self._abort_playback.set()
