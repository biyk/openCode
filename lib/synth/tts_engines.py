"""Движки синтеза речи (миксин TTS)."""

import os
import tempfile
import wave
from pathlib import Path
from typing import Any, Optional

from gtts import gTTS

_BASE_DIR = Path(__file__).resolve().parents[2]
_PIPER_MODEL = _BASE_DIR / "models" / "piper" / "ru_RU-irina-medium.onnx"


class TtsEnginesMixin:
    """Миксин TextToSpeech: gTTS, Piper, временные файлы."""

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

    @staticmethod
    def _temp_file(suffix: str) -> str:
        """Создаёт временный файл с указанным суффиксом и возвращает путь."""
        temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        temp_path = temp_file.name
        temp_file.close()
        return temp_path
