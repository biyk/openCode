import json
import os
import platform
import subprocess
from typing import Optional

from lib.tts import TextToSpeech

CONFIRMATION_PHRASE = os.environ.get("VOICE_CONFIRMATION_PHRASE")


class CommandMatcher:
    """Сопоставление голосовых команд с shell-командами."""

    def __init__(self, commands_file: str):
        self._commands_file = commands_file
        self._mtime = 0.0
        self._data = self._load()
        self._tts = TextToSpeech()

    def _load(self) -> dict:
        try:
            with open(self._commands_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            self._mtime = os.path.getmtime(self._commands_file)
        except Exception:
            self._data = {}
        return self._data

    def reload(self) -> None:
        """Перечитывает файл команд, если он изменился с момента последней загрузки."""
        try:
            mtime = os.path.getmtime(self._commands_file)
        except OSError:
            return
        if mtime == self._mtime:
            return
        self._load()

    def _get_command(self, cmd_id: str) -> Optional[str]:
        """Возвращает команду с учётом платформы."""
        commands = self._data.get("commands", {})
        cmd = commands.get(cmd_id)
        if cmd is None:
            return None
        if isinstance(cmd, dict):
            system = platform.system().lower()
            return cmd.get(system) or cmd.get("default")
        return cmd

    def find(self, text: str) -> Optional[str]:
        """Находит команду по шаблону в тексте."""
        self.reload()
        text_lower = text.lower()
        match = self._data.get("match", {})
        commands = self._data.get("commands", {})
        for cmd_id, templates in match.items():
            for template in templates:
                if template in text_lower:
                    return self._get_command(cmd_id) or cmd_id
        return None

    def execute(self, text: str) -> bool:
        """Находит и выполняет команду через shell."""
        self.reload()
        command = self.find(text)
        if command:
            try:
                subprocess.run(command, shell=True, check=True)
                if os.environ.get("VOICE_CONFIRMATION_PHRASE"):
                    self._tts.speak_and_play(os.environ["VOICE_CONFIRMATION_PHRASE"])
                return True
            except subprocess.CalledProcessError:
                return False
        return False

    def get_llm_config(self) -> dict:
        """Возвращает конфигурацию для LLM."""
        return self._data.get("llm", {})
