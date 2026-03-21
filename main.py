import os
import sys
import json
import queue
import threading
import zipfile
from typing import Optional

from lib.output import TranscriptionOutput
from lib.commands import CommandMatcher

import sounddevice as sd
import requests
from vosk import Model, KaldiRecognizer, SetLogLevel

COMMANDS_FILE = os.path.join(os.path.dirname(__file__), "commands.json")

# ---------- Configuration ----------
DEFAULT_SR = 16000
BLOCKSIZE = 2048          # frames per audio callback

# Vosk models (small, ~50–60 MB each)
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

# ---------- Model download ----------
def ensure_vosk_model(lang_code: str) -> str:
    """
    Ensure Vosk model is present. If missing, download and unzip.
    Returns path to the model directory.
    """
    info = VOSK_MODELS[lang_code]
    model_dir = os.path.join(MODELS_DIR, info["name"])

    # Check if model already exists
    if os.path.isdir(model_dir) and os.path.exists(os.path.join(model_dir, "am", "final.mdl")):
        return model_dir

    print(f"Downloading Vosk model for {lang_code}...")
    url = info["zip_url"]
    zip_path = os.path.join(MODELS_DIR, info["name"] + ".zip")

    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        # Extract
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(MODELS_DIR)

        # Remove zip
        os.remove(zip_path)

        # Ensure model directory is returned correctly
        extracted_dirs = [d for d in os.listdir(MODELS_DIR) if d.startswith(info["name"])]
        if extracted_dirs:
            model_dir = os.path.join(MODELS_DIR, extracted_dirs[0])

        print("Model ready.")
        return model_dir

    except Exception as e:
        raise RuntimeError(f"Failed to download Vosk model for {lang_code}: {e}")

# ---------- STT worker (thread) ----------
class TranscriptionWorker:
    """
    Captures audio and prints final transcriptions to stdout.
    """
    def __init__(self, lang_code: str = "ru"):
        self.lang_code = lang_code
        self._running = threading.Event()
        self._running.set()
        self._queue = queue.Queue()
        self._accumulated = []
        self._output = TranscriptionOutput()
        self._matcher = CommandMatcher(COMMANDS_FILE)

    def audio_callback(self, indata, frames, time_info, status):
        """Called by sounddevice for each audio chunk."""
        if status:
            pass
        self._queue.put(bytes(indata))

    def run(self):
        """Main loop – runs until stop() is called."""
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

                    if recognizer.AcceptWaveform(data):
                        res = json.loads(recognizer.Result())
                        text = res.get("text", "").strip()
                        if text:
                            self._accumulated.append(text)
                            command = self._matcher.find(text)
                            if command:
                                self._output.print_text(command)
                            else:
                                self._output.print_text(text)
                    else:
                        pass

                final = json.loads(recognizer.FinalResult())
                final_text = final.get("text", "").strip()
                if final_text:
                    self._accumulated.append(final_text)
                    command = self._matcher.find(final_text)
                    if command:
                        self._output.print_text(command)
                    else:
                        self._output.print_text(final_text)

        except Exception as e:
            self._output.print_error(f"STT error: {e}")
        finally:
            self._output.print_stopped()

    def stop(self):
        self._running.clear()

# ---------- Main ----------
def main():
    lang = "ru"

    output = TranscriptionOutput()
    worker = TranscriptionWorker(lang_code=lang)

    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()

    output.print_info("\n🎙️  Recording... Press Enter to stop.\n")
    input()

    worker.stop()
    thread.join(timeout=2)
    output.print_info("Exiting.")

if __name__ == "__main__":
    main()

