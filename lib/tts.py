import os
import re
import subprocess
import tempfile
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

from gtts import gTTS

from lib.logger import Logger

_BASE_DIR = Path(__file__).resolve().parents[1]
_SAPI_SCRIPT = _BASE_DIR / "bin" / "tts_sapi.ps1"
_PIPER_MODEL = _BASE_DIR / "models" / "piper" / "ru_RU-irina-medium.onnx"


class TextToSpeech:
    """Синтез речи с офлайн-фолбэком.

    Основной движок — Google Translate TTS (gTTS). При недоступности сети
    используется локальная нейросеть Piper, а при её недоступности —
    системный голос Windows (System.Speech через PowerShell).
    После первого сетевого сбоя оставшиеся блоки синтезируются офлайн.
    Многосложный текст разбивается на блоки и синтезируется параллельно
    (пайплайн): пока первый блок проигрывается, следующие готовятся
    в фоне. Аудио всегда проигрывается строго в порядке исходного текста.
    """

    _SENTENCE_RE = re.compile(r"(?<=[.!?…,;:—–-])\s+")

    def __init__(self, lang: str = "ru", max_workers: int = 4,
                 gtts_timeout: float = 8.0):
        self._lang = lang
        self._max_workers = max_workers
        self._gtts_timeout = gtts_timeout
        self._offline = False
        self._logger = Logger()
        self._piper_lock = threading.Lock()
        self._piper_voice: Optional[Any] = None
        self._piper_error = False

    def _split_sentences(self, text: str) -> list[str]:
        """Разбивает текст на блоки, сохраняя их порядок."""
        parts = [p.strip() for p in self._SENTENCE_RE.split(text)]
        return [p for p in parts if p] or [text.strip()]

    def speak(self, text: str) -> Optional[str]:
        """Синтез речи блока в файл (mp3/wav) с офлайн-фолбэком."""
        if not text:
            print("[TTS] Пустой текст")
            return None

        print(f"[TTS] Синтез: {text[:50]}{'...' if len(text) > 50 else ''}")

        if not self._offline:
            audio_path = self._speak_gtts(text)
            if audio_path:
                return audio_path
            print("[TTS] gTTS недоступен, переключаюсь в офлайн-режим")
            self._offline = True

        audio_path = self._speak_piper(text)
        if audio_path:
            return audio_path

        print("[TTS] Piper недоступен, пробую системный голос")
        return self._speak_sapi(text)

    def _speak_gtts(self, text: str) -> Optional[str]:
        """Синтез через Google Translate TTS в MP3."""
        temp_path = self._temp_file(".mp3")
        try:
            tts = gTTS(text=text, lang=self._lang, slow=False,
                       timeout=self._gtts_timeout)
            tts.save(temp_path)
            print(f"[TTS] gTTS: сохранено {temp_path}")
            return temp_path
        except Exception as e:
            print(f"[TTS] Ошибка gTTS: {e}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None

    def _speak_piper(self, text: str) -> Optional[str]:
        """Синтез через локальную нейросеть Piper в WAV."""
        voice = self._get_piper_voice()
        if voice is None:
            return None
        temp_path = self._temp_file(".wav")
        try:
            with wave.open(temp_path, "wb") as out:
                voice.synthesize_wav(text, out)
            print(f"[TTS] Piper: сохранено {temp_path}")
            return temp_path
        except Exception as e:
            print(f"[TTS] Ошибка Piper: {e}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None

    def _get_piper_voice(self) -> Optional[Any]:
        """Лениво загружает модель Piper (один раз, потокобезопасно)."""
        if self._piper_error:
            return None
        with self._piper_lock:
            if self._piper_voice is not None:
                return self._piper_voice
            if self._piper_error:
                return None
            try:
                if not _PIPER_MODEL.exists():
                    print(f"[TTS] Модель Piper не найдена: {_PIPER_MODEL}")
                    self._piper_error = True
                    return None
                from piper.voice import PiperVoice
                print("[TTS] Piper: загрузка модели...")
                self._piper_voice = PiperVoice.load(str(_PIPER_MODEL))
            except Exception as e:
                print(f"[TTS] Ошибка загрузки Piper: {e}")
                self._piper_error = True
                return None
            return self._piper_voice

    def _speak_sapi(self, text: str) -> Optional[str]:
        """Синтез через системный голос Windows (System.Speech) в WAV."""
        if not _SAPI_SCRIPT.exists():
            print(f"[TTS] Скрипт SAPI не найден: {_SAPI_SCRIPT}")
            return None
        temp_path = self._temp_file(".wav")
        text_file = self._temp_file(".txt")
        try:
            with open(text_file, "w", encoding="utf-8") as f:
                f.write(text)
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(_SAPI_SCRIPT), "-TextFile", text_file,
                 "-OutFile", temp_path],
                check=True, capture_output=True, timeout=30)
            if os.path.getsize(temp_path) == 0:
                print("[TTS] SAPI не создал аудио")
                os.unlink(temp_path)
                return None
            print(f"[TTS] SAPI: сохранено {temp_path}")
            return temp_path
        except Exception as e:
            print(f"[TTS] Ошибка SAPI: {e}")
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None
        finally:
            if os.path.exists(text_file):
                os.unlink(text_file)

    @staticmethod
    def _temp_file(suffix: str) -> str:
        """Создаёт временный файл с указанным суффиксом и возвращает путь."""
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        temp_path = temp_file.name
        temp_file.close()
        return temp_path

    def _play_file(self, audio_path: str) -> None:
        """Воспроизводит аудиофайл по расширению и удаляет его."""
        try:
            if audio_path.lower().endswith(".wav"):
                self._play_wav(audio_path)
            else:
                self._play_mp3(audio_path)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)

    def _play_wav(self, audio_path: str) -> None:
        """Воспроизводит WAV через System.Media.SoundPlayer."""
        print("[TTS] Воспроизведение WAV через SoundPlayer...")
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command",
                 f"(New-Object System.Media.SoundPlayer '{audio_path}').PlaySync()"],
                check=True, timeout=120)
            print("[TTS] Воспроизведение завершено")
        except subprocess.TimeoutExpired:
            print("[TTS] Таймаут воспроизведения WAV")
        except Exception as e:
            print(f"[TTS] Ошибка воспроизведения WAV: {e}")

    def _play_mp3(self, audio_path: str) -> None:
        """Воспроизводит MP3 через mpg123, при его отсутствии через ffplay."""
        try:
            print("[TTS] Воспроизведение через mpg123...")
            subprocess.run(["mpg123", "-q", audio_path], check=True)
            print("[TTS] Воспроизведение завершено")
        except FileNotFoundError:
            print("[TTS] mpg123 не найден, пробую ffplay...")
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                     audio_path],
                    check=True)
                print("[TTS] Воспроизведение завершено")
            except FileNotFoundError:
                print("[TTS] ffplay не найден")

    def _speak_and_play_single(self, text: str,
                               on_finished: Optional[Callable[[], None]]) -> None:
        """Синтез и проигрывание одного блока."""
        audio_path = self.speak(text)
        if not audio_path:
            print("[TTS] Воспроизведение отменено - файл не создан")
            if on_finished:
                on_finished()
            return
        self._play_file(audio_path)
        if on_finished:
            on_finished()

    def _speak_and_play_pipeline(self, text: str,
                                 on_finished: Optional[Callable[[], None]]) -> None:
        """Параллельный синтез блоков и последовательное проигрывание."""
        sentences = self._split_sentences(text)
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = [pool.submit(self.speak, s) for s in sentences]
            for future in futures:
                audio_path = future.result()
                if audio_path:
                    self._play_file(audio_path)
        if on_finished:
            on_finished()

    def speak_and_play(self, text: str,
                       on_finished: Optional[Callable[[], None]] = None) -> None:
        """Синтез речи и воспроизведение.

        Текст длиннее одного блока синтезируется по блокам параллельно,
        проигрывается строго по порядку.
        """
        if not text:
            print("[TTS] Пустой текст")
            if on_finished:
                on_finished()
            return

        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            self._speak_and_play_single(text, on_finished)
        else:
            self._speak_and_play_pipeline(text, on_finished)
