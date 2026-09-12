import json
import os
import platform
import subprocess
from typing import Optional

from lib.tts import TextToSpeech

CONFIRMATION_PHRASE = os.environ.get("VOICE_CONFIRMATION_PHRASE")

DEFAULT_TRIGGERS = ["пожалуйста", "алиса"]


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

    @property
    def triggers(self) -> list[str]:
        """Список триггеров для активации команд/LLM."""
        return self._data.get("triggers", DEFAULT_TRIGGERS)

    def has_trigger(self, text: str) -> bool:
        """Проверяет наличие любого триггера в тексте (case-insensitive)."""
        text_lower = text.lower()
        return any(t in text_lower for t in self.triggers)

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
        """Находит команду по шаблону в тексте (только если есть триггер)."""
        self.reload()
        if not self.has_trigger(text):
            return None
        text_lower = text.lower()
        match = self._data.get("match", {})
        for cmd_id, templates in match.items():
            for template in templates:
                if template in text_lower:
                    return self._get_command(cmd_id) or cmd_id
        return None

    def get_command(self, cmd_id: str) -> Optional[str]:
        """Возвращает shell-команду по id с учётом платформы."""
        self.reload()
        return self._get_command(cmd_id)

    def execute(self, text: str) -> bool:
        """Находит и выполняет команду через shell."""
        self.reload()
        command = self.find(text)
        if command:
            return self._run(command)
        return False

    def execute_by_id(self, cmd_id: str) -> bool:
        """Выполняет команду по id через shell (для мини-коррекции)."""
        self.reload()
        command = self._get_command(cmd_id)
        if not command:
            return False
        return self._run(command)

    def _run(self, command: str) -> bool:
        """Запускает shell-команду и возвращает успех."""
        try:
            subprocess.run(command, shell=True, check=True)
            if os.environ.get("VOICE_CONFIRMATION_PHRASE"):
                self._tts.speak_and_play(os.environ["VOICE_CONFIRMATION_PHRASE"])
            return True
        except subprocess.CalledProcessError:
            return False

    def get_llm_config(self) -> dict:
        """Возвращает конфигурацию для LLM."""
        return self._data.get("llm", {})

    def get_intent_config(self) -> dict:
        """Возвращает конфигурацию интеллектуального классификатора команд."""
        return self._data.get("intent", {})

    def match_config(self) -> dict:
        """Возвращает словарь {command_id: [фразы]} для классификатора."""
        return self._data.get("match", {})

    def get_skills_config(self) -> dict:
        """Возвращает конфигурацию скиллов."""
        return self._data.get("skills", {})
