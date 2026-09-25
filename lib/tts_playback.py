"""Проигрывание аудио и конвейер озвучки (миксин TTS)."""

import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

_BASE_DIR = Path(__file__).resolve().parents[1]
_SAPI_SCRIPT = _BASE_DIR / "bin" / "tts_sapi.ps1"


class TtsPlaybackMixin:
    """Миксин TextToSpeech: SAPI, плееры, параллельный конвейер."""

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

        Плеер detach'ится от консоли: иначе mpg123 снимает с неё
        QuickEdit (выделение/копирование), а по abort не успевает вернуть.
        Возвращает True при нормальном завершении, False при прерывании
        по abort_event. При превышении таймаута поднимает TimeoutExpired.
        """
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW)
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
