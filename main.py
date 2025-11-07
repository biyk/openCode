import os
import sys
import json
import queue
import threading
import zipfile
import time
from dataclasses import dataclass
from typing import Optional, List

from dotenv import load_dotenv

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QPlainTextEdit, QTextEdit, QComboBox, QCheckBox, QLineEdit, QMessageBox
)

import requests
import sounddevice as sd
import numpy as np
from vosk import Model, KaldiRecognizer, SetLogLevel

# ------------- Config -------------

APP_NAME = "Voice → Summary → Email (OpenRouter + Vosk)"

DEFAULT_SR = 16000
BLOCKSIZE = 2048  # frames per audio callback

# Small models (≈50–60 MB)
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

# ------------- Utils -------------

def ensure_vosk_model(lang_code: str) -> str:
    """
    Ensure Vosk model is present. If missing, download and unzip.
    Returns path to the model directory.
    """
    info = VOSK_MODELS[lang_code]
    model_dir = os.path.join(MODELS_DIR, info["name"])
    if os.path.isdir(model_dir) and os.path.exists(os.path.join(model_dir, "am", "final.mdl")) or os.path.isdir(model_dir):
        return model_dir

    import zipfile, io, requests, shutil
    url = info["zip_url"]
    fname = os.path.join(MODELS_DIR, info["name"] + ".zip")
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            size_mb = int(r.headers.get("Content-Length", 0)) / (1024 * 1024)
            downloaded = 0
            with open(fname, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # Optional: progress print to console
        with zipfile.ZipFile(fname, "r") as zf:
            zf.extractall(MODELS_DIR)
        # Some zip archives unpack into a dir with the same name; ensure final path
        # If unpacked folder isn't exactly name, leave as is but return found dir
        unpacked = [os.path.join(MODELS_DIR, d) for d in os.listdir(MODELS_DIR) if d.startswith(info["name"]) and os.path.isdir(os.path.join(MODELS_DIR, d))]
        if unpacked:
            model_dir = unpacked[0]
        # Remove archive to save space
        try:
            os.remove(fname)
        except OSError:
            pass
        return model_dir
    except Exception as e:
        raise RuntimeError(f"Не удалось скачать модель Vosk {lang_code}: {e}")

# ------------- OpenRouter client -------------

class OpenRouterClient:
    def __init__(self, api_key: str, referer: Optional[str] = None, title: Optional[str] = None, model: str = "deepseek/deepseek-r1-distill-llama-70b:free"):
        self.api_key = api_key
        self.referer = referer or "https://local.app"
        self.title = title or "PyQt Voice Demo"
        self.model = model
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def summarize_and_email(self, transcript_text: str, audience: str, translate_to_en: bool) -> dict:
        """
        Ask the LLM to produce 5 bullets and a short polite email.
        Returns dict with keys: bullets(list[str]), subject, email_ru, email_en(optional)
        """
        system = (
            "You are a precise assistant. Read the transcript of a 1-minute meeting/lecture summary. "
            "Produce JSON only, no prose. Fields: "
            "bullets (array of exactly 5 short items, max 16 words each, imperative or indicative), "
            "email_subject (<=80 chars), "
            "email_ru (5-8 concise sentences, polite, includes agreements and next steps), "
            "email_en (if translate=true, an English translation of email_ru; otherwise an empty string). "
            "Adapt tone for audience: Teachers | Students | Business. "
            "Do not include markdown or code fences."
        )

        user = {
            "transcript": transcript_text,
            "audience": audience,
            "translate": translate_to_en
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.referer,
            "X-Title": self.title,
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(user, ensure_ascii=False)}
            ],
            # Safer non-streaming for simple demos
            "stream": False,
            "temperature": 0.2,
            "max_tokens": 700
        }

        try:
            r = requests.post(self.endpoint, headers=headers, data=json.dumps(payload), timeout=120)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            raise RuntimeError(f"API request failed: {e}")
        except json.JSONDecodeError:
            raise RuntimeError("API response is not valid JSON")

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected API response structure: {e}")

        # Try parse JSON first
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: naive extraction, assuming content is the email text
            result = {
                "bullets": [],
                "email_subject": "Резюме встречи",
                "email_ru": content,
                "email_en": "" if not translate_to_en else ""
            }
        # Normalize keys
        bullets = result.get("bullets") or result.get("summary") or []
        subject = result.get("email_subject") or "Резюме встречи"
        email_ru = result.get("email_ru") or ""
        email_en = result.get("email_en") or ""
        return {
            "bullets": bullets,
            "subject": subject,
            "email_ru": email_ru,
            "email_en": email_en
        }

# ------------- STT worker -------------

class STTWorker(QThread):
    partial_text = pyqtSignal(str)
    final_text = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, lang_code: str = "ru", parent=None):
        super().__init__(parent)
        self.lang_code = lang_code
        self._running = threading.Event()
        self._running.set()
        self._queue = queue.Queue()
        self._stream = None
        self._accumulated = []

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            # status has .input_overflow etc.
            pass
        # Convert to 16-bit little-endian bytes
        self._queue.put(bytes(indata))

    def run(self):
        try:
            # Reduce Vosk logging
            SetLogLevel(0)
            model_path = ensure_vosk_model(self.lang_code)
            model = Model(model_path)
            rec = KaldiRecognizer(model, DEFAULT_SR)
            rec.SetWords(True)

            with sd.RawInputStream(samplerate=DEFAULT_SR, blocksize=BLOCKSIZE, dtype="int16",
                                   channels=1, callback=self.audio_callback):
                while self._running.is_set():
                    try:
                        data = self._queue.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if rec.AcceptWaveform(data):
                        res = json.loads(rec.Result())
                        text = res.get("text", "").strip()
                        if text:
                            self._accumulated.append(text)
                            self.final_text.emit(" ".join(self._accumulated))
                    else:
                        res = json.loads(rec.PartialResult())
                        p = res.get("partial", "").strip()
                        if p:
                            # emit partial
                            self.partial_text.emit(" ".join(self._accumulated + [p]))
                # flush final
                res = json.loads(rec.FinalResult())
                ftext = res.get("text", "").strip()
                if ftext:
                    self._accumulated.append(ftext)
                    self.final_text.emit(" ".join(self._accumulated))
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._running.clear()

# ------------- Main Window -------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(980, 720)

        load_dotenv()
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            QMessageBox.critical(self, "Ошибка", "Не найден OPENROUTER_API_KEY в .env или окружении.")
            sys.exit(1)

        self.client = OpenRouterClient(
            api_key=api_key,
            referer=os.environ.get("OPENROUTER_REFERER"),
            title=os.environ.get("OPENROUTER_TITLE"),
        )

        # UI
        central = QWidget()
        layout = QVBoxLayout(central)

        # Controls row
        row = QHBoxLayout()
        self.lang_box = QComboBox()
        self.lang_box.addItems(["ru", "en"])
        self.lang_box.setCurrentText("ru")
        row.addWidget(QLabel("Язык речи:"))
        row.addWidget(self.lang_box)

        self.audience_box = QComboBox()
        self.audience_box.addItems(["Teachers", "Students", "Business"])
        row.addSpacing(16)
        row.addWidget(QLabel("Аудитория письма:"))
        row.addWidget(self.audience_box)

        self.chk_translate = QCheckBox("Перевести письмо на английский")
        row.addSpacing(16)
        row.addWidget(self.chk_translate)

        row.addStretch()

        self.btn_start = QPushButton("Старт")
        self.btn_stop = QPushButton("Стоп")
        self.btn_summarize = QPushButton("Суммаризировать")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        row.addWidget(self.btn_summarize)

        layout.addLayout(row)

        # Live transcript
        layout.addWidget(QLabel("Живое распознавание:"))
        self.txt_live = QPlainTextEdit()
        self.txt_live.setReadOnly(True)
        self.txt_live.setPlaceholderText("Говорите в микрофон после нажатия Старт...")
        self.txt_live.setMinimumHeight(180)
        layout.addWidget(self.txt_live)

        # Summary bullets
        layout.addWidget(QLabel("Краткий конспект (5 пунктов):"))
        self.txt_bullets = QPlainTextEdit()
        self.txt_bullets.setReadOnly(True)
        layout.addWidget(self.txt_bullets)

        # Subject + email RU
        sub_row = QHBoxLayout()
        self.edt_subject = QLineEdit()
        self.edt_subject.setPlaceholderText("Тема письма")
        sub_row.addWidget(QLabel("Тема:"))
        sub_row.addWidget(self.edt_subject)
        layout.addLayout(sub_row)

        layout.addWidget(QLabel("Письмо (RU):"))
        self.txt_email_ru = QTextEdit()
        layout.addWidget(self.txt_email_ru)

        layout.addWidget(QLabel("Email (EN, если включён перевод):"))
        self.txt_email_en = QTextEdit()
        layout.addWidget(self.txt_email_en)

        self.setCentralWidget(central)

        # Events
        self.btn_start.clicked.connect(self.start_stt)
        self.btn_stop.clicked.connect(self.stop_stt)
        self.btn_summarize.clicked.connect(self.do_summarize)

        self.stt_thread: Optional[STTWorker] = None

    # ------ slots ------
    def start_stt(self):
        if self.stt_thread and self.stt_thread.isRunning():
            return
        lang = self.lang_box.currentText()
        self.txt_live.clear()
        self.stt_thread = STTWorker(lang_code=lang)
        self.stt_thread.partial_text.connect(self.on_partial)
        self.stt_thread.final_text.connect(self.on_final)
        self.stt_thread.error.connect(self.on_error)
        self.stt_thread.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def stop_stt(self):
        if self.stt_thread and self.stt_thread.isRunning():
            self.stt_thread.stop()
            self.stt_thread.wait(3000)
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def on_partial(self, text: str):
        self.txt_live.setPlainText(text)
        self.txt_live.verticalScrollBar().setValue(self.txt_live.verticalScrollBar().maximum())

    def on_final(self, text: str):
        self.txt_live.setPlainText(text)
        self.txt_live.verticalScrollBar().setValue(self.txt_live.verticalScrollBar().maximum())

    def on_error(self, message: str):
        QMessageBox.critical(self, "Ошибка STT", message)
        self.stop_stt()

    def do_summarize(self):
        # Stop STT if running
        if self.stt_thread and self.stt_thread.isRunning():
            self.stop_stt()

        transcript = self.txt_live.toPlainText().strip()
        if not transcript:
            QMessageBox.warning(self, "Пусто", "Нет текста для суммаризации.")
            return

        self.btn_summarize.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = self.client.summarize_and_email(
                transcript_text=transcript,
                audience=self.audience_box.currentText(),
                translate_to_en=self.chk_translate.isChecked()
            )
            # Fill UI
            bullets = res.get("bullets", [])
            self.txt_bullets.setPlainText("\n".join(f"• {b}" for b in bullets))
            self.edt_subject.setText(res.get("subject", ""))
            self.txt_email_ru.setPlainText(res.get("email_ru", ""))
            self.txt_email_en.setPlainText(res.get("email_en", ""))
        except Exception as e:
            QMessageBox.critical(self, "Ошибка LLM", str(e))
        finally:
            QApplication.restoreOverrideCursor()
            self.btn_summarize.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
