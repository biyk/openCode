"""Исполнение шагов скиллов (миксин реестра)."""

import platform
import subprocess


class SkillActionsMixin:
    """Миксин SkillRegistry: open_url / run_cmd шаги."""

    def _execute_step(self, step, params: dict) -> bool:
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
