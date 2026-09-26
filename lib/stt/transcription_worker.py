"""Голосовой цикл: захват аудио, Vosk STT, оркестратор команд."""
import json
import os
import queue
import sys
import threading
from typing import Optional

from lib.voice_cmd.aliases import AliasStore
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path
from lib.voice_cmd.intent import build_intent
from lib.core.laya_decision import build_decision
from lib.core.logger import Logger
from lib.opencode.opencode_cli import OpenCodeCliRunner
from lib.core.orchestrator import Orchestrator
from lib.core.output import TranscriptionOutput
from lib.providers.manager import ProviderManager
from lib.runtime.status import StatusStore
from lib.tts import TextToSpeech
from lib.stt import vosk_model as _vm

import sounddevice as sd
from vosk import Model, KaldiRecognizer, SetLogLevel

_provider_manager = ProviderManager()
# ---------- Конфигурация ----------
DEFAULT_SR = 16000       # Частота дискретизации
BLOCKSIZE = 2048         # Размер блока аудио

# Сколько секунд после озвучки игнорировать микрофон (хвост эха TTS)
AUDIO_SUPPRESS_AFTER_TTS = 0.5
# Слова, которые прерывают озвучку
STOP_WORDS = frozenset(("стоп", "останови", "stop", "хватит", "прекрати"))


def _fix_encoding(text: str) -> str:
    """Чинит битый текст Vosk на Windows (cp866 -> utf-8).

    Корректную кириллицу возвращает как есть.
    """
    if not text or sys.platform != "win32":
        return text
    if any("\u0410" <= ch <= "\u044F" or ch in "\u0401\u0451" for ch in text):
        return text
    try:
        encoded = text.encode("cp866", errors="ignore")
        return encoded.decode("utf-8", errors="ignore")
    except Exception:
        return text


class TranscriptionWorker:
    """Захватывает аудио и распознаёт речь."""

    def __init__(self, lang_code: str = "ru", device_name: str = "default",
                 output: Optional[TranscriptionOutput] = None):
        self.lang_code = lang_code
        self._running = threading.Event()
        self._running.set()
        self._queue = queue.Queue()
        self._accumulated = []
        self._output = output or TranscriptionOutput()
        commands_file = get_device_commands_path(device_name)
        self._status = StatusStore(
            StatusStore.path_for_commands_file(commands_file),
            output=self._output,
        )
        self._status.start()
        self._matcher = CommandMatcher(commands_file, status_store=self._status)
        self._logger = Logger()

        llm_config = self._matcher.get_llm_config()
        history_limit = llm_config.get("history_limit", 10)
        self._llm = _provider_manager.get_client(history_limit=history_limit)
        if hasattr(self._llm, "_set_output"):
            self._llm._set_output(self._output)
        self._tts = TextToSpeech()

        intent = build_intent(self._matcher, self._llm)
        # Decision-слой Laya (заменяет mini-intent, когда настроен);
        # intent не создаём — новый путь его не использует.
        self._decision = build_decision(self._matcher, self._output)
        self._orchestrator = Orchestrator(
            matcher=self._matcher,
            output=self._output,
            tts=self._tts,
            stop_words=STOP_WORDS,
            suppress_after=AUDIO_SUPPRESS_AFTER_TTS,
            intent=intent,
            decision=self._decision,
            on_exit=self._dev_mode_exit,
        )

        # Алиасы (база соответствий П6.0, всегда активны — детерминированы)
        self._aliases = AliasStore(
            AliasStore.path_for_commands_file(commands_file))
        self._orchestrator._aliases = self._aliases

        # Фолбэк: console opencode (скиллы из cli/.opencode/skill),
        # флаг opencode_cli.enabled в commands.json
        opencode_config = self._matcher.get_opencode_cli_config()
        if opencode_config.get("enabled"):
            self._opencode = OpenCodeCliRunner(
                model=opencode_config.get("model", "omnirouter/auto/tools"),
                output=self._output,
            )
            self._orchestrator._opencode = self._opencode

    def audio_callback(self, indata, frames, time_info, status):
        """Пишет аудио в очередь (и во время озвучки — для стоп-слов)."""
        self._queue.put(bytes(indata))

    def run(self):
        """Основной цикл - работает до вызова stop()."""
        try:
            SetLogLevel(0)
            model_path = _vm.ensure_vosk_model(self.lang_code)
            model = Model(model_path)
            recognizer = KaldiRecognizer(model, DEFAULT_SR)
            recognizer.SetWords(True)
            stop_recognizer = KaldiRecognizer(
                model, DEFAULT_SR, json.dumps(sorted(STOP_WORDS)))

            with sd.RawInputStream(
                samplerate=DEFAULT_SR,
                blocksize=BLOCKSIZE,
                dtype="int16",
                channels=1,
                callback=self.audio_callback
            ):
                while self._running.is_set():
                    try:
                        data = self._queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    # Распознанный текст
                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        text = _fix_encoding(res.get("text", "")).strip()
                        if text:
                            self._logger.log_command(text)
                            self._accumulated.append(text)
                            self._process_text(text)
                    else:
                        # Частичные результаты: буфер забит эхом озвучки,
                        # стоп-слово ловим не дожидаясь финала.
                        partial = json.loads(
                            recognizer.PartialResult()).get("partial", "").strip()
                        if partial:
                            partial = _fix_encoding(partial)
                            if partial and self._orchestrator.maybe_abort(partial):
                                recognizer.Reset()

                    # Точный детектор стоп-слов по грамматике: работает всё время
                    # озвучки, диктовочная модель тонет в аудио TTS.
                    if self._orchestrator.speaking:
                        if stop_recognizer.AcceptWaveform(data):
                            stop_text = json.loads(
                                stop_recognizer.Result()).get("text", "").strip()
                            stop_text = _fix_encoding(stop_text)
                            if stop_text and self._orchestrator.maybe_abort(stop_text):
                                recognizer.Reset()
                                stop_recognizer.Reset()

                # Финальный результат при остановке
                final = json.loads(recognizer.FinalResult())
                final_text = _fix_encoding(final.get("text", "")).strip()
                if final_text:
                    self._logger.log_command(final_text)
                    self._accumulated.append(final_text)
                    self._process_text(final_text)

        except Exception as e:
            self._output.print_error(f"Ошибка STT: {e}")
        finally:
            self._output.print_stopped()

    def _process_text(self, text: str) -> None:
        """Обрабатывает распознанный текст через оркестратор."""
        self._orchestrator.process_text(text)

    def _dev_mode_exit(self) -> None:
        """Выход из приложения по голосовой команде (режим разработки)."""
        self._output.print_info("[DevMode] Выход из приложения")
        self.stop()
        os._exit(0)

    def stop(self):
        self._running.clear()
        if getattr(self, "_status", None) is not None:
            self._status.stop()
        if getattr(self, "_decision", None) is not None:
            self._decision.close()
        self._orchestrator.stop()
