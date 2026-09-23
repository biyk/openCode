import json
import os
import platform
import subprocess
from typing import Optional

from lib.commands_config import CommandConfigMixin
from lib.commands_match import CommandMatchMixin
from lib.status import StatusStore
from lib.tts import TextToSpeech

CONFIRMATION_PHRASE = os.environ.get("VOICE_CONFIRMATION_PHRASE")

DEFAULT_TRIGGERS = ["пожалуйста", "алиса"]


def _fmt_number(value: float) -> str:
    """Форматирует число для подстановки в shell-команду."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


class CommandMatcher(CommandMatchMixin, CommandConfigMixin):
    """Сопоставление голосовых команд с shell-командами.

    Каждая команда может требовать статусы ("requires": {"id": [...]}):
    команда выполняется только если все её статусы активны в StatusStore.
    Составные команды описываются в "sequences": {"id": {"steps": [...]}},
    после успешного шага выставляются его "provides"-статусы.
    """

    def __init__(self, commands_file: str,
                 status_store: Optional[StatusStore] = None):
        self._commands_file = commands_file
        self._mtime = 0.0
        self._data = self._load()
        self._tts = TextToSpeech()
        self._status_store = status_store

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

    def _get_command(self, cmd_id: str,
                     settings: tuple[str, ...] = ()) -> Optional[str]:
        """Возвращает команду с учётом платформы и настроек.

        Настройки {немного}/{сильно} меняют числовые параметры
        (например {{step}}): множитель из секции "settings".
        Плейсхолдер {{text}} подставляет свободный текст — все слова,
        идущие после команды (для calendar-reminder/task-add).
        Кавычки вокруг {{text}} ставит сам шаблон; двойные кавычки
        внутри текста вырезаются, чтобы не разорвать shell-команду.
        """
        commands = self._data.get("commands", {})
        cmd = commands.get(cmd_id)
        if cmd is None:
            return None
        if not isinstance(cmd, dict):
            if "{{text}}" in cmd:
                text = " ".join(settings).replace('"', "").strip()
                return cmd.replace("{{text}}", text)
            return cmd
        system = platform.system().lower()
        template = cmd.get(system) or cmd.get("default")
        if template is None:
            return None
        params = {}
        for key, value in cmd.items():
            if key in ("linux", "windows", "darwin", "default"):
                continue
            if isinstance(value, dict):
                value = value.get(system) or value.get("default")
            if isinstance(value, (int, float)):
                params[key] = value
        for word in settings:
            mults = self.settings_for(cmd_id).get(word, {})
            for param, factor in mults.items():
                if param in params and isinstance(factor, (int, float)):
                    params[param] = params[param] * factor
        for name, value in params.items():
            token = "{{" + name + "}}"
            if token in template:
                template = template.replace(token, _fmt_number(value))
        if "{{text}}" in template:
            text = " ".join(settings).replace('"', "").strip()
            template = template.replace("{{text}}", text)
        return template

    def get_command(self, cmd_id: str,
                    settings: tuple[str, ...] = ()) -> Optional[str]:
        """Возвращает shell-команду по id с учётом платформы."""
        self.reload()
        return self._get_command(cmd_id, settings)

    def execute_by_id(self, cmd_id: str,
                      settings: tuple[str, ...] = ()) -> bool:
        """Выполняет команду по id (или составную sequence по шагам)."""
        self.reload()
        seq = self.sequences().get(cmd_id)
        if seq is not None:
            return self._execute_sequence(cmd_id, seq, settings)
        return self._execute_step(cmd_id, settings)

    def _execute_step(self, cmd_id: str,
                      settings: tuple[str, ...] = ()) -> bool:
        """Выполняет один шаг: проверка requires, shell, provides."""
        if self.missing_requires(cmd_id):
            return False
        command = self._get_command(cmd_id, settings)
        if not command:
            return False
        if not self._run(command):
            return False
        self._mark_provides(cmd_id)
        return True

    def _execute_sequence(self, seq_id: str, seq: dict,
                          settings: tuple[str, ...] = ()) -> bool:
        """Выполняет шаги составной команды по очереди до первой ошибки."""
        if self.missing_requires(seq_id):
            return False
        for step in seq.get("steps", []):
            if not self._execute_step(step, settings):
                return False
        self._mark_provides(seq_id)
        return True

    def _mark_provides(self, cmd_id: str) -> None:
        """Оптимистично выставляет provides-статусы после успеха."""
        if self._status_store is None:
            return
        for name in self.provides_for(cmd_id):
            self._status_store.set(name, True)

    def _run(self, command: str) -> bool:
        """Запускает shell-команду и возвращает успех."""
        try:
            subprocess.run(command, shell=True, check=True)
            if os.environ.get("VOICE_CONFIRMATION_PHRASE"):
                self._tts.speak_and_play(os.environ["VOICE_CONFIRMATION_PHRASE"])
            return True
        except subprocess.CalledProcessError:
            return False
