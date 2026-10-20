import base64
import re
import sys
import threading
from typing import Any, Callable, Optional

from lib.core.logger import Logger
from lib.core.output import stamp_stdio
from lib.runtime.speak_gate import build_speak_gate
from lib.synth import tts_cache
from lib.synth.tts_engines import TtsEnginesMixin
from lib.synth.tts_pipeline import TtsPipelineMixin
from lib.synth.tts_playback import TtsPlaybackMixin

# ВРЕМЕННО: озвучка только мужским Piper (Denis). При True выключены все
# женские генераторы — gTTS (системный Google-голос ru всегда женский),
# фолбэк SAPI (голос Irina) — и чтение mp3-кэша gTTS (иначе прежние фразы
# играли бы женским). Модель задаётся в lib/synth/tts_engines.py.
# Откат: поставить False (и вернуть прежнюю модель при необходимости).
DENIS_ONLY = False


class TextToSpeech(TtsEnginesMixin, TtsPipelineMixin, TtsPlaybackMixin):
    """Синтез речи с офлайн-фолбэком.

    Основной движок — Google Translate TTS (gTTS). При недоступности сети
    используется локальная нейросеть Piper, а при её недоступности —
    системный голос Windows (System.Speech через PowerShell).
    После первого сетевого сбоя оставшиеся блоки синтезируются офлайн.
    Многосложный текст разбивается на блоки и синтезируется параллельно
    (пайплайн): пока первый блок проигрывается, следующие готовятся
    в фоне. Аудио всегда проигрывается строго в порядке исходного текста.
    Голос звучит только в наушниках — вне них молчаливый режим (§4.14).
    """

    _SENTENCE_RE = re.compile(r"(?<=[.!?…,;:—–-])\s+")

    def __init__(self, lang: str = "ru", max_workers: int = 4,
                 gtts_timeout: float = 8.0, output: Any = None):
        self._lang = lang
        self._max_workers = max_workers
        self._gtts_timeout = gtts_timeout
        # В режиме «только Denis» сразу офлайн: gTTS (женский) пропускается.
        self._offline = DENIS_ONLY
        self._logger = Logger()
        self._piper_lock = threading.Lock()
        self._piper_voice: Optional[Any] = None
        self._piper_error = False
        # Счётчик играющих блоков и слушатель переключений (шлюз захвата,
        # §4.6) — их ведёт миксин TtsPlaybackMixin.
        self._play_lock = threading.Lock()
        self._play_depth = 0
        self._voice_listener: Optional[Callable[[bool], None]] = None
        # Шлюз озвучки (§4.14): вслух говорим, только когда вывод идёт в
        # наушники. Секция speak_gate читается один раз здесь — так правило
        # действует и в живом процессе, и в каждом `python -m lib.…`.
        self._speak_gate: Optional[Any] = build_speak_gate(output=output)
        # Слышен ли был последний блок: в молчаливом режиме эха нет, и окно
        # эхо-затишья после фразы не нужно (§6, читает оркестратор).
        self.audible = True

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

        cached = None if DENIS_ONLY else tts_cache.cached_copy(self._lang, text)
        if cached:
            print(f"[TTS] Кэш: {text[:50]}{'...' if len(text) > 50 else ''}")
            return cached

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

        if DENIS_ONLY:
            print("[TTS] Piper (Denis) не дал аудио; gTTS/SAPI выключены")
            return None

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
    stamp_stdio()  # у дочернего процесса свой stdout — метки ставим здесь
    raise SystemExit(main())
