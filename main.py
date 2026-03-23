import os
import sys
import json
import queue
import threading
import zipfile
import socket
from typing import Optional

from lib.output import TranscriptionOutput
from lib.commands import CommandMatcher
from lib.openrouter import OpenRouterClient
from lib.logger import Logger
from lib.tts import TextToSpeech
from lib.config_loader import get_device_commands_path

import sounddevice as sd
import requests
from vosk import Model, KaldiRecognizer, SetLogLevel

# ---------- Конфигурация ----------
DEFAULT_SR = 16000       # Частота дискретизации
BLOCKSIZE = 2048         # Размер блока аудио
LLM_TRIGGER = "пожалуйста"  # Кодовое слово для активации LLM

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
    def __init__(self, lang_code: str = "ru", device_name: str = "default"):
        self.lang_code = lang_code
        self._running = threading.Event()
        self._running.set()
        self._queue = queue.Queue()
        self._accumulated = []
        self._output = TranscriptionOutput()
        commands_file = get_device_commands_path(device_name)
        self._matcher = CommandMatcher(commands_file)
        self._logger = Logger()

        llm_config = self._matcher.get_llm_config()
        history_limit = llm_config.get("history_limit", 10)
        self._llm = OpenRouterClient(history_limit=history_limit)
        self._tts = TextToSpeech()

    def audio_callback(self, indata, frames, time_info, status):
        """Обратный вызов sounddevice для каждого блока аудио."""
        if status:
            pass
        self._queue.put(bytes(indata))

    def run(self):
        """Основной цикл - работает до вызова stop()."""
        try:
            SetLogLevel(0)
            model_path = ensure_vosk_model(self.lang_code)
            model = Model(model_path)
            recognizer = KaldiRecognizer(model, DEFAULT_SR)
            recognizer.SetWords(True)

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
                        text = res.get("text", "").strip()
                        if text:
                            self._logger.log_command(text)
                            self._accumulated.append(text)
                            command = self._matcher.find(text)
                            if command:
                                self._matcher.execute(text)
                                self._output.print_text(command)
                            else:
                                if LLM_TRIGGER in text.lower():
                                    self._output.print_info(f"[LLM] Запрос: {text}")
                                    answer = self._llm.ask(text)
                                    if answer:
                                        self._output.print_text(answer)
                                        self._tts.speak_and_play(answer)
                                    else:
                                        self._output.print_error("[LLM] Ошибка ответа")
                                        self._output.print_text(text)
                                else:
                                    self._output.print_text(text)

                # Финальный результат при остановке
                final = json.loads(recognizer.FinalResult())
                final_text = final.get("text", "").strip()
                if final_text:
                    self._logger.log_command(final_text)
                    self._accumulated.append(final_text)
                    command = self._matcher.find(final_text)
                    if command:
                        self._matcher.execute(final_text)
                        self._output.print_text(command)
                    else:
                        if LLM_TRIGGER in final_text.lower():
                            self._output.print_info(f"[LLM] Запрос: {final_text}")
                            answer = self._llm.ask(final_text)
                            if answer:
                                self._output.print_text(answer)
                                self._tts.speak_and_play(answer)
                            else:
                                self._output.print_error("[LLM] Ошибка ответа")
                                self._output.print_text(final_text)
                        else:
                            self._output.print_text(final_text)

        except Exception as e:
            self._output.print_error(f"Ошибка STT: {e}")
        finally:
            self._output.print_stopped()

    def stop(self):
        self._running.clear()

# ---------- Главная функция ----------
def main():
    lang = "ru"
    device_name = socket.gethostname()

    output = TranscriptionOutput()
    worker = TranscriptionWorker(lang_code=lang, device_name=device_name)

    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()

    output.print_info("\n🎙️  Запись... Нажмите Enter для остановки.\n")
    input()

    worker.stop()
    thread.join(timeout=2)
    output.print_info("Выход.")

if __name__ == "__main__":
    main()
