import base64
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
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

    def _play_file(self, audio_path: str, abort_event: Optional[threading.Event] = None) -> None:
        """Воспроизводит аудиофайл по расширению и удаляет его."""
        try:
            if audio_path.lower().endswith(".wav"):
                self._play_wav(audio_path, abort_event)
            else:
                self._play_mp3(audio_path, abort_event)
        finally:
            # Плеер может быть ещё живым после abort и держать файл —
            # WinError 32 (файл занят) не должен ронять поток озвучки.
            try:
                if os.path.exists(audio_path):
                    os.unlink(audio_path)
            except OSError:
                pass

    def _play_wav(self, audio_path: str,
                  abort_event: Optional[threading.Event] = None) -> None:
        """Воспроизводит WAV через System.Media.SoundPlayer."""
        print("[TTS] Воспроизведение WAV через SoundPlayer...")
        try:
            finished = self._run_player(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command",
                 f"(New-Object System.Media.SoundPlayer '{audio_path}').PlaySync()"],
                abort_event, timeout=120)
            if finished:
                print("[TTS] Воспроизведение завершено")
        except subprocess.TimeoutExpired:
            print("[TTS] Таймаут воспроизведения WAV")
        except Exception as e:
            print(f"[TTS] Ошибка воспроизведения WAV: {e}")

    def _play_mp3(self, audio_path: str,
                  abort_event: Optional[threading.Event] = None) -> None:
        """Воспроизводит MP3 через mpg123, при его отсутствии через ffplay."""
        try:
            print("[TTS] Воспроизведение через mpg123...")
            if self._run_player(["mpg123", "-q", audio_path], abort_event):
                print("[TTS] Воспроизведение завершено")
        except FileNotFoundError:
            print("[TTS] mpg123 не найден, пробую ffplay...")
            try:
                finished = self._run_player(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                     audio_path],
                    abort_event)
                if finished:
                    print("[TTS] Воспроизведение завершено")
            except FileNotFoundError:
                print("[TTS] ffplay не найден")

    @staticmethod
    def _run_player(cmd: list[str],
                    abort_event: Optional[threading.Event] = None,
                    timeout: float = 120.0) -> bool:
        """Запускает плеер с возможностью прерывания.

        Возвращает True при нормальном завершении, False при прерывании
        по abort_event. При превышении таймаута поднимает TimeoutExpired.
        """
        proc = subprocess.Popen(cmd)
        deadline = time.time() + timeout
        try:
            while proc.poll() is None:
                if abort_event is not None and abort_event.is_set():
                    proc.terminate()
                    print("[TTS] Воспроизведение прервано")
                    return False
                if time.time() >= deadline:
                    proc.terminate()
                    raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)
                time.sleep(0.05)
            if proc.returncode != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd)
            return True
        except Exception:
            proc.terminate()
            raise

    def _speak_and_play_single(self, text: str,
                               on_finished: Optional[Callable[[], None]],
                               abort_event: Optional[threading.Event] = None) -> None:
        """Синтез и проигрывание одного блока."""
        if abort_event is not None and abort_event.is_set():
            print("[TTS] Воспроизведение прервано")
            if on_finished:
                on_finished()
            return
        audio_path = self.speak(text, abort_event)
        if not audio_path:
            print("[TTS] Воспроизведение отменено - файл не создан")
            if on_finished:
                on_finished()
            return
        if abort_event is not None and abort_event.is_set():
            print("[TTS] Воспроизведение прервано")
            if on_finished:
                on_finished()
            return
        self._play_file(audio_path, abort_event)
        if on_finished:
            on_finished()

    def _speak_and_play_pipeline(self, text: str,
                                 on_finished: Optional[Callable[[], None]],
                                 abort_event: Optional[threading.Event] = None) -> None:
        """Параллельный синтез блоков и последовательное проигрывание.

        При срабатывании abort_event синтез оставшихся блоков отменяется
        (ожидающие задачи отменяются, активная продолжается в фоне без блокировки).
        """
        sentences = self._split_sentences(text)
        pool = ThreadPoolExecutor(max_workers=self._max_workers)
        try:
            futures = [pool.submit(self.speak, s, abort_event) for s in sentences]
            for future in futures:
                if abort_event is not None and abort_event.is_set():
                    break
                audio_path = future.result()
                if audio_path:
                    self._play_file(audio_path, abort_event)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if on_finished:
            on_finished()

    def speak_and_play(self, text: str,
                       on_finished: Optional[Callable[[], None]] = None,
                       abort_event: Optional[threading.Event] = None) -> None:
        """Синтез речи и воспроизведение.

        Текст длиннее одного блока синтезируется по блокам параллельно,
        проигрывается строго по порядку. abort_event позволяет прервать
        озвучку в любой момент.
        """
        if not text:
            print("[TTS] Пустой текст")
            if on_finished:
                on_finished()
            return

        sentences = self._split_sentences(text)
        if len(sentences) <= 1:
            self._speak_and_play_single(text, on_finished, abort_event)
        else:
            self._speak_and_play_pipeline(text, on_finished, abort_event)


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
