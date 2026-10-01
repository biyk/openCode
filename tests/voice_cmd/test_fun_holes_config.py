"""Сторожевые тесты конфига дыр календаря (fun_holes).

Двигатель и проводка покрыты tests/taskflow/test_fun_fill.py и
tests/core/test_task_monitor.py, но потеря функционала была не в коде:
функционал глох, когда из targets/<host>/commands.json пропадала секция
`fun_holes` (или её enabled) — все тесты при этом оставались зелёными,
потому что мокали конфиг друг о друге. Здесь — проверка самого конфига:
аксессор get_fun_holes_config и живой файл устройства.
"""

import json
import os
import platform

import pytest

from lib.voice_cmd.commands import CommandMatcher


def _matcher(tmp_path, data):
    """CommandMatcher поверх временного commands.json."""
    path = os.path.join(str(tmp_path), "commands.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return CommandMatcher(path)


class TestFunHolesAccessor:
    """get_fun_holes_config / get_task_monitor_config — секции commands.json."""

    def test_section_passthrough(self, tmp_path):
        """Секция fun_holes отдаётся как есть, с enabled и параметрами."""
        matcher = _matcher(tmp_path, {
            "fun_holes": {"enabled": True, "min_gap_min": 1,
                          "lookback_days": 7},
        })
        assert matcher.get_fun_holes_config() == {
            "enabled": True, "min_gap_min": 1, "lookback_days": 7,
        }

    def test_missing_section_is_empty_dict(self, tmp_path):
        """Без секции fun_holes — пустой dict (фича выключена, не ошибка)."""
        matcher = _matcher(tmp_path, {"commands": {}, "match": {}})
        assert matcher.get_fun_holes_config() == {}

    def test_task_monitor_section_passthrough(self, tmp_path):
        """Секция task_monitor (интервал, по которому живёт хук fun) читаема."""
        matcher = _matcher(tmp_path, {
            "task_monitor": {"enabled": True, "interval_min": 10},
        })
        assert matcher.get_task_monitor_config() == {
            "enabled": True, "interval_min": 10,
        }


def _device_config():
    """Живой commands.json текущего устройства; None, если файла нет."""
    path = os.path.join("targets", platform.node(), "commands.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestDeviceConfigGuards:
    """Функционал не должен молча умирать от правок конфига устройства."""

    def test_device_json_is_parseable(self):
        """Конфиг устройства — валидный JSON (ручные правки не ломают старт)."""
        if _device_config() is None:
            pytest.skip("на этом устройстве нет targets/<host>/commands.json")

    def test_fun_holes_stays_enabled(self):
        """Если секция fun_holes есть в конфиге — она обязана быть включена.

        Случайное выключение (правка enabled, потеря секции при склейке)
        глушит «Отдых» без единого звука — все остальные тесты зелёные.
        """
        data = _device_config()
        if data is None:
            pytest.skip("на этом устройстве нет targets/<host>/commands.json")
        section = data.get("fun_holes")
        if section is None:
            pytest.skip("устройство не использует fun_holes")
        assert section.get("enabled"), (
            "fun_holes.enabled выключен — дыры календаря перестанут "
            "заполняться; включить обратно, если это не сознательное решение"
        )
        assert "min_gap_min" in section or "lookback_days" in section, (
            "секция fun_holes есть, но параметров дыр в ней нет — "
            "make_fun_fill заработает на дефолтах tuning незаметно"
        )

    def test_task_monitor_stays_enabled(self):
        """task_monitor — поток, который дёргает хук fun каждый цикл."""
        data = _device_config()
        if data is None:
            pytest.skip("на этом устройстве нет targets/<host>/commands.json")
        section = data.get("task_monitor")
        if section is None:
            pytest.skip("устройство не использует task_monitor")
        assert section.get("enabled"), (
            "task_monitor.enabled выключен — ни вопросов, ни дыр календаря"
        )

    def test_fun_holes_needs_task_monitor(self):
        """Другие включённые секции того же потока не рассинхронизированы:
        fun_holes не может быть включён при выключенном task_monitor."""
        data = _device_config()
        if data is None:
            pytest.skip("на этом устройстве нет targets/<host>/commands.json")
        fun = data.get("fun_holes") or {}
        mon = data.get("task_monitor") or {}
        if fun.get("enabled") and not mon.get("enabled"):
            pytest.fail(
                "fun_holes включён, а task_monitor выключен: хук дыр "
                "никогда не вызовется (make_fun_fill собирает его только "
                "внутри start_task_monitor)"
            )
