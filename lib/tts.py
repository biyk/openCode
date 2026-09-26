import base64
import re
import sys
import threading
from typing import Any, Optional

from lib.core.logger import Logger
from lib.synth.tts_engines import TtsEnginesMixin
from lib.synth.tts_playback import TtsPlaybackMixin


class TextToSpeech(TtsEnginesMixin, TtsPlaybackMixin):
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

    def speak(self, text: str,
              abort_event: Optional[threading.Event] = None) -> Optional[str]:
        """Синтез речи блока в файл (mp3/wav) с офлайн-фолбэком."""
        if abort_event is not None and abort_event.is_set():
            print("[TTS] Синтез прерван")
            return None
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


def _decode_arg(raw: str) -> str:
    """Декодирует аргумент CLI: --b64:<base64> или обычный текст.

    base64 позволяет передать кириллицу и кавычки в python -m lib.tts
    без проблем кодировки консоли Windows (cp1251 vs utf-8).
    """
    raw = raw.strip()
    if raw.startswith("--b64:") or raw.startswith("--b64="):
        payload = raw.split(":", 1)[1] if ":" in raw[:6] else raw[6:]
        try:
            return base64.b64decode(payload).decode("utf-8")
        except Exception:
            return raw
    return raw


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.tts "текст"` или `python -m lib.tts --b64:…`.

    Аргументами служат фразы для озвучки; безопасно работает со
    встроенными кавычками и кириллицей через base64.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m lib.tts <текст> | --b64:<base64>")
        return 2
    text = " ".join(_decode_arg(a) for a in args)
    try:
        TextToSpeech().speak_and_play(text)
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"[TTS] CLI: ошибка озвучки: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
