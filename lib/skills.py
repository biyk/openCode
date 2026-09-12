"""Реестр и исполнитель скиллов (статические, детерминированные).

Скилл — JSON-манифест в targets/<host>/skills/<skill>.json:
{
  "name": "skill_name",
  "description": "Описание",
  "phrases": ["фраза 1", "фраза 2"],
  "params": {"param1": {"type": "str", "required": true}},
  "steps": [
    {"action": "open_url", "url": "https://..."},
    {"action": "run_cmd", "cmd": "..."}
  ]
}

Загрузчик ищет файлы *.json в папке skills, кэширует, даёт match() по фразам.
"""

import json
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from lib.logger import Logger


@dataclass
class SkillStep:
    """Один шаг скилла."""
    action: str
    params: dict[str, Any]


@dataclass
class SkillManifest:
    """Манифест скилла."""
    name: str
    description: str
    phrases: list[str]
    params: dict[str, dict[str, Any]]
    steps: list[SkillStep]


class SkillRegistry:
    """Реестр скиллов: загрузка, поиск по фразе, исполнение."""

    def __init__(self, skills_dir: str, logger: Optional[Logger] = None):
        self._skills_dir = Path(skills_dir)
        self._logger = logger or Logger()
        self._skills: dict[str, SkillManifest] = {}
        self._phrase_index: dict[str, str] = {}  # phrase_lower -> skill_name
        self._loaded = False

    def load(self) -> None:
        """Загружает все *.json из папки скиллов."""
        if self._loaded:
            return
        self._skills.clear()
        self._phrase_index.clear()
        if not self._skills_dir.exists():
            self._logger.log_info(f"[Skills] Папка не существует: {self._skills_dir}")
            self._loaded = True
            return
        for path in self._skills_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                manifest = self._parse_manifest(data)
                self._skills[manifest.name] = manifest
                for phrase in manifest.phrases:
                    self._phrase_index[phrase.lower()] = manifest.name
                self._logger.log_info(f"[Skills] Загружен скилл: {manifest.name}")
            except Exception as e:
                self._logger.log_error(f"[Skills] Ошибка загрузки {path}: {e}")
        self._loaded = True

    def reload(self) -> None:
        """Принудительно перечитывает файлы скиллов."""
        self._loaded = False
        self.load()

    def _parse_manifest(self, data: dict) -> SkillManifest:
        steps = [SkillStep(action=s["action"], params=s.get("params", {}))
                 for s in data.get("steps", [])]
        return SkillManifest(
            name=data["name"],
            description=data.get("description", ""),
            phrases=data.get("phrases", []),
            params=data.get("params", {}),
            steps=steps,
        )

    def match(self, text: str) -> Optional[str]:
        """Возвращает имя скилла, если текст точно совпадает с одной из фраз (case-insensitive)."""
        self.load()
        text_lower = text.lower().strip()
        return self._phrase_index.get(text_lower)

    def get_skill(self, name: str) -> Optional[SkillManifest]:
        self.load()
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        self.load()
        return list(self._skills.keys())

    def execute(self, skill_name: str, params: Optional[dict] = None) -> bool:
        """Исполняет скилл по имени с заданными параметрами."""
        self.load()
        skill = self._skills.get(skill_name)
        if not skill:
            self._logger.log_error(f"[Skills] Скилл не найден: {skill_name}")
            return False

        # Валидация параметров
        validated = self._validate_params(skill.params, params or {})
        if validated is None:
            return False

        self._logger.log_info(f"[Skills] Исполняю {skill_name} с params={validated}")
        for step in skill.steps:
            if not self._execute_step(step, validated):
                self._logger.log_error(f"[Skills] Шаг не выполнен: {step.action}")
                return False
        return True

    def _validate_params(self, schema: dict, provided: dict) -> Optional[dict]:
        result = {}
        for name, spec in schema.items():
            required = spec.get("required", False)
            ptype = spec.get("type", "str")
            if name not in provided:
                if required:
                    self._logger.log_error(f"[Skills] Обязательный параметр отсутствует: {name}")
                    return None
                continue
            value = provided[name]
            # Простая проверка типа
            if ptype == "int":
                try:
                    value = int(value)
                except ValueError:
                    self._logger.log_error(f"[Skills] Параметр {name} должен быть int")
                    return None
            elif ptype == "float":
                try:
                    value = float(value)
                except ValueError:
                    self._logger.log_error(f"[Skills] Параметр {name} должен быть float")
                    return None
            result[name] = value
        return result

    def _execute_step(self, step: SkillStep, params: dict) -> bool:
        action = step.action
        step_params = step.params

        # Подстановка параметров из validated params
        resolved = {}
        for k, v in step_params.items():
            if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                param_name = v[2:-1]
                if param_name in params:
                    resolved[k] = params[param_name]
                else:
                    self._logger.log_error(f"[Skills] Параметр шага не найден: {param_name}")
                    return False
            else:
                resolved[k] = v

        try:
            if action == "open_url":
                return self._action_open_url(resolved)
            elif action == "run_cmd":
                return self._action_run_cmd(resolved)
            else:
                self._logger.log_error(f"[Skills] Неизвестное действие: {action}")
                return False
        except Exception as e:
            self._logger.log_error(f"[Skills] Ошибка исполнения {action}: {e}")
            return False

    def _action_open_url(self, p: dict) -> bool:
        url = p.get("url")
        if not url:
            self._logger.log_error("[Skills] open_url: нет url")
            return False
        system = platform.system().lower()
        try:
            if system == "windows":
                subprocess.run(["cmd", "/c", "start", "", url], check=True)
            elif system == "darwin":
                subprocess.run(["open", url], check=True)
            else:
                subprocess.run(["xdg-open", url], check=True)
            self._logger.log_info(f"[Skills] Открыт URL: {url}")
            return True
        except subprocess.CalledProcessError as e:
            self._logger.log_error(f"[Skills] Ошибка открытия URL: {e}")
            return False

    def _action_run_cmd(self, p: dict) -> bool:
        cmd = p.get("cmd")
        if not cmd:
            self._logger.log_error("[Skills] run_cmd: нет cmd")
            return False
        try:
            subprocess.run(cmd, shell=True, check=True)
            self._logger.log_info(f"[Skills] Команда выполнена: {cmd}")
            return True
        except subprocess.CalledProcessError as e:
            self._logger.log_error(f"[Skills] Ошибка команды: {e}")
            return False


def get_skills_dir() -> Path:
    """Возвращает путь к папке скиллов для текущего хоста."""
    from lib.config_loader import get_device_commands_path
    commands_path = Path(get_device_commands_path(platform.node()))
    return commands_path.parent / "skills"
