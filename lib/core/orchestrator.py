"""Оркестратор обработки голосового ввода (детерминированное ядро).

Решает, на каком уровне обрабатывать распознанный текст:
1. commands.json (дословное совпадение + алиасы),
2. decision-слой Laya (дисижн-модель; commands.json не совпало),
3. (legacy, когда decision не настроен) mini-LLM intent → opencode-cli.

Фолбэк после промаха Лайи — LLM-детект команды (OmniRouter/LM Studio,
миксин orchestrator_llm): по смыслу выбирает id, для команд с параметром
вторым запросом вычленяет значение {{text}}.
"""

import queue
import threading
import time
from typing import Any, Callable, Optional

from lib.voice_cmd.commands import CommandMatcher
from lib.opencode.opencode_cli import OpenCodeCliRunner
from lib.core.orchestrator_ask import OrchestratorAskMixin
from lib.core.orchestrator_chat import OrchestratorChatMixin
from lib.core.orchestrator_decision import OrchestratorDecisionMixin
from lib.core.orchestrator_event_match import OrchestratorEventMatchMixin
from lib.core.orchestrator_flavor import OrchestratorFlavorMixin
from lib.core.orchestrator_llm import OrchestratorLlmMixin
from lib.core.orchestrator_memory import OrchestratorMemoryMixin
from lib.core.orchestrator_opencode import OrchestratorOpencodeMixin
from lib.core.orchestrator_speech import OrchestratorSpeechMixin
from lib.core.output import TranscriptionOutput


class Orchestrator(
    OrchestratorAskMixin,
    OrchestratorChatMixin,
    OrchestratorDecisionMixin,
    OrchestratorEventMatchMixin,
    OrchestratorFlavorMixin,
    OrchestratorLlmMixin,
    OrchestratorMemoryMixin,
    OrchestratorOpencodeMixin,
    OrchestratorSpeechMixin,
):
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
        knowledge: Any = None,
        opencode: Optional[OpenCodeCliRunner] = None,
        decision: Any = None,
        llm: Any = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        self._matcher = matcher
        self._output = output
        self._tts = tts
        self._stop_words = stop_words
        self._suppress_after = suppress_after
        self._clear_speech_buffer = clear_speech_buffer or (lambda: None)
        self._intent = intent or None
        self._knowledge = knowledge or None
        self._opencode = opencode or None
        self._decision = decision or None
        self._llm = llm or None
        self._event_matcher = None
        self._on_exit = on_exit or None
        self._dev_mode = False
        self._speaking = False
        self._abort_playback = threading.Event()
        self._suppress_until = 0.0
        self._opencode_queue: queue.Queue[
            tuple[str, bool, Optional[Callable[[str], None]]]] = queue.Queue()
        self._opencode_worker: Optional[threading.Thread] = None
        self._opencode_active = False
        self._pending_ask = None
        self._reply = None
        # Строки микрофона и сообщения чата идут в один пайплайн: общее
        # состояние (озвучка, ожидаемый ответ) не должно рваться
        # посередине обработки другого источника.
        self._input_lock = threading.Lock()
        self._init_flavor()

    @property
    def dev_mode(self) -> bool:
        """Включён ли режим разработки (все фразы → модель напрямую)."""
        return self._dev_mode

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

    def process_text(self, text: str,
                     reply: Optional[Callable[[str], None]] = None) -> None:
        """Обрабатывает текст: стоп-слово, команда или запрос к LLM.

        reply — канал ответа для текстового источника (Telegram): строка
        пришла готовым текстом, а не звуком с колонок, поэтому окна
        эхо-затишья и ранней озвучки к ней не применяются, а ответы уходят
        в чат вместо динамиков (см. orchestrator_chat).
        """
        with self._input_lock:
            chat = self._begin_request(reply)
            if not chat:
                if time.monotonic() < self._suppress_until:
                    return
                if self._speaking:
                    self.maybe_abort(text)
                    return
            if self._opencode_active and self.maybe_abort(text):
                # Пока opencode думает, стоп-слово только отменяет ожидаемый ответ
                return
            if self._handle_dev_mode_controls(text):
                return
            if self._dev_mode:
                # Режим разработки: все фразы напрямую в модель, без матчера.
                self._output.print_text(text)
                self._output.print_info(
                    "[DevMode] Фраза передана в модель напрямую")
                self._enqueue_opencode(text, raw=True)
                return
            # Сначала выводим распознанный текст в консоль и лог
            self._output.print_text(text)
            # Ответ на заданный фоном вопрос — не команда: перехватываем строку
            # раньше уровней commands.json (см. orchestrator_ask).
            if self._take_ask_answer(text):
                return
            # 1..3. commands.json → база знаний → Laya/legacy → opencode-cli.
            self._process_commands_level(text)

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
