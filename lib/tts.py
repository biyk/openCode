import tempfile
from typing import Optional, Callable

from gtts import gTTS

from lib.logger import Logger


class TextToSpeech:
    """Синтез речи через Google Translate TTS."""

    def __init__(self, lang: str = "ru"):
        self._lang = lang
        self._logger = Logger()

    def speak(self, text: str) -> Optional[str]:
        """Синтез речи и сохранение в MP3."""
        if not text:
            print("[TTS] Пустой текст")
            return None

        print(f"[TTS] Синтез: {text[:50]}{'...' if len(text) > 50 else ''}")

        temp_file = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_path = temp_file.name
        temp_file.close()

        try:
            tts = gTTS(text=text, lang=self._lang, slow=False)
            tts.save(temp_path)
            print(f"[TTS] Сохранено: {temp_path}")
            return temp_path
        except Exception as e:
            print(f"[TTS] Ошибка синтеза: {e}")
            return None

    def speak_and_play(self, text: str, on_finished: Optional[Callable[[], None]] = None) -> None:
        """Синтез речи и воспроизведение."""
        audio_path = self.speak(text)
        if not audio_path:
            print("[TTS] Воспроизведение отменено - файл не создан")
            if on_finished:
                on_finished()
            return

        import subprocess
        try:
            print("[TTS] Воспроизведение через mpg123...")
            subprocess.run(["mpg123", "-q", audio_path], check=True)
            print("[TTS] Воспроизведение завершено")
        except FileNotFoundError:
            print("[TTS] mpg123 не найден, пробую ffplay...")
            try:
                subprocess.run(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path],
                    check=True
                )
                print("[TTS] Воспроизведение завершено")
            except FileNotFoundError:
                print("[TTS] ffplay не найден")
        finally:
            import os
            if os.path.exists(audio_path):
                os.unlink(audio_path)
            if on_finished:
                on_finished()
