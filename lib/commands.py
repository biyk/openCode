import os
import json
import subprocess
from typing import Optional


class CommandMatcher:
    def __init__(self, commands_file: str):
        self._commands_file = commands_file
        self._data = self._load()

    def _load(self) -> dict:
        try:
            with open(self._commands_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def find(self, text: str) -> Optional[str]:
        text_lower = text.lower()
        match = self._data.get("match", {})
        commands = self._data.get("commands", {})
        for cmd_id, templates in match.items():
            for template in templates:
                if template in text_lower:
                    return commands.get(cmd_id, cmd_id)
        return None

    def execute(self, text: str) -> bool:
        command = self.find(text)
        if command:
            try:
                subprocess.run(command, shell=True, check=True)
                return True
            except subprocess.CalledProcessError:
                return False
        return False
