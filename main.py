import os
import sys
import json
import queue
import threading
import zipfile
import socket
from typing import Optional

# Добавить mpg123 в PATH (Windows)
mpg_path = os.path.join(os.path.dirname(__file__), "bin", "mpg")
if os.path.isdir(mpg_path):
    os.environ["PATH"] = mpg_path + os.pathsep + os.environ.get("PATH", "")

# Исправить кодировку консоли Windows (Vosk возвращает cp866/utf-8 мусор на Windows)
if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

def _fix_encoding(text: str) -> str:
    """Пытается исправить битый текст от Vosk на Windows (cp866 -> utf-8)."""
    if not text or sys.platform != "win32":
        return text
    try:
        encoded = text.encode("cp866", errors="ignore")
        return encoded.decode("utf-8", errors="ignore")
    except Exception:
        return text

from lib.output import TranscriptionOutput
from lib.commands import CommandMatcher
from lib.logger import Logger
from lib.tts import TextToSpeech
from lib.config_loader import get_device_commands_path
from lib.orchestrator import Orchestrator
from lib.skills import SkillRegistry, get_skills_dir
from lib.intent import IntentClassifier
from lib.media import is_media_playing
from lib.providers.manager import ProviderManager

import sounddevice as sd
import requests
from vosk import Model, KaldiRecognizer, SetLogLevel

_provider_manager = ProviderManager()

# ---------- Конфигурация ----------
DEFAULT_SR = 16000       # Частота дискретизации
BLOCKSIZE = 2048         # Размер блока аудио

# Сколько секунд после озвучки игнорировать микрофон (хвост эха TTS)
AUDIO_SUPPRESS_AFTER_TTS = 0.5
# Слова, которые прерывают озвучку
STOP_WORDS = frozenset(("стоп", "останови", "stop", "хватит", "прекрати"))

# Модели Vosk (маленькие, ~50-60 МБ)
VOSK_MODELS = {
    "ru": {
        "name": "vosk-model-small-ru-0.22",
        "zip_url": "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip",
    },
    "en": {
        "name": "vosk-model-small-en-us-0.15",
        "zip_url": "https://alphacephei.com/kaldi/models/vosk-model-small-en-us-0.15.zip",
    }
}

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# ---------- Загрузка модели ----------
def ensure_vosk_model(lang_code: str) -> str:
    """Проверяет наличие модели Vosk, скачивает при необходимости."""
    info = VOSK_MODELS[lang_code]
    model_dir = os.path.join(MODELS_DIR, info["name"])

    if os.path.isdir(model_dir) and os.path.exists(os.path.join(model_dir, "am", "final.mdl")):
        return model_dir

    print(f"Загрузка модели Vosk для {lang_code}...")
    url = info["zip_url"]
    zip_path = os.path.join(MODELS_DIR, info["name"] + ".zip")

    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(MODELS_DIR)

        os.remove(zip_path)

        extracted_dirs = [d for d in os.listdir(MODELS_DIR) if d.startswith(info["name"])]
        if extracted_dirs:
            model_dir = os.path.join(MODELS_DIR, extracted_dirs[0])

        print("Модель готова.")
        return model_dir

    except Exception as e:
        raise RuntimeError(f"Ошибка загрузки модели для {lang_code}: {e}")

# ---------- Обработка аудио ----------
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
        self._matcher = CommandMatcher(commands_file)
        self._logger = Logger()

        llm_config = self._matcher.get_llm_config()
        history_limit = llm_config.get("history_limit", 10)
        self._llm = _provider_manager.get_client(history_limit=history_limit)
        if hasattr(self._llm, "_set_output"):
            self._llm._set_output(self._output)
        self._tts = TextToSpeech()

        intent_config = self._matcher.get_intent_config()
        intent = None
        if intent_config.get("enabled"):
            media_probe = None
            if intent_config.get("include_media", True):
                media_probe = is_media_playing
            intent = IntentClassifier(
                commands=self._matcher.match_config(),
                llm=self._llm,
                media_probe=media_probe,
            )
        self._orchestrator = Orchestrator(
            matcher=self._matcher,
            output=self._output,
            llm=self._llm,
            tts=self._tts,
            stop_words=STOP_WORDS,
            suppress_after=AUDIO_SUPPRESS_AFTER_TTS,
            intent=intent,
            skills=None,  # будет инициализирован ниже если включен
        )

        # Skills (после создания оркестратора, чтобы skills имел доступ к output через оркестратор)
        skills_config = self._matcher.get_skills_config()
        if skills_config.get("enabled"):
            skills = SkillRegistry(
                skills_dir=str(get_skills_dir()),
                logger=self._logger,
            )
            self._orchestrator._skills = skills

    def audio_callback(self, indata, frames, time_info, status):
        """Обратный вызов sounddevice для каждого блока аудио.

        Данные записываются всегда, даже во время озвучки, чтобы можно
        было прервать её словом из STOP_WORDS.
        """
        self._queue.put(bytes(indata))

    def run(self):
        """Основной цикл - работает до вызова stop()."""
        try:
            SetLogLevel(0)
            model_path = ensure_vosk_model(self.lang_code)
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
                        # Стоп-слово может не дождаться финального результата —
                        # буфер распознавания забит аудио озвучки, поэтому ловим
                        # его тоже в частичных результатах.
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

    def stop(self):
        self._running.clear()
        self._orchestrator.stop()

# ---------- Главная функция ----------
def main():
    lang = "ru"
    device_name = socket.gethostname()

    output = TranscriptionOutput()
    worker = TranscriptionWorker(lang_code=lang, device_name=device_name,
                                 output=output)

    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()

    output.print_info("\n🎙️  Запись... Нажмите Enter для остановки.\n")
    input()

    worker.stop()
    thread.join(timeout=2)
    output.print_info("Выход.")

if __name__ == "__main__":
    main()
