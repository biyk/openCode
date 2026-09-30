# TOOLTIP: Статистика использования команд: счётчик вызовов по cmd_id в JSON-файле
"""Учёт частоты выполнения команд — чтобы видно было, что можно удалить.

Каждый успешный запуск команды (CommandMatcher.execute_by_id) прибавляет
единицу в JSON рядом с commands.json устройства:

    {"cmd_id": {"count": N, "first_seen": iso, "last_seen": iso}}

Команды, которых в файле нет, — никогда не выполнялись. Отчёт
`python -m lib.voice_cmd.command_stats` сводит известные id commands.json и
счётчик: по возрастанию использования, чтобы «мёртвое» было сверху.

Сбой чтения/записи НЕ должен ломать выполнение команды: все ошибки
пишутся swallowed (fail-open — статистика важна, но не ценой команды).
"""

import json
import os
import sys
import threading
from datetime import datetime
from typing import Optional

from lib.core.errors import swallowed

STATS_FILENAME = "command_stats.json"


def stats_path_for(commands_file: str) -> str:
    """Путь к файлу статистики — в той же папке, что commands.json устройства."""
    folder = os.path.dirname(commands_file)
    return os.path.join(folder, STATS_FILENAME)


class CommandStats:
    """Потокобезопасный счётчик запусков команд в JSON-файле."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def snapshot(self) -> dict:
        """Содержимое файла статистики (пустой dict при отсутствии/сбое)."""
        try:
            with open(self._path, encoding="utf-8") as file:
                data = json.load(file)
        except FileNotFoundError:
            return {}
        except Exception as exc:  # noqa: BLE001 - статистика не валит команду
            return swallowed(f"command_stats.read({self._path})", exc, {})
        return data if isinstance(data, dict) else {}

    def bump(self, cmd_id: str, when: Optional[datetime] = None) -> None:
        """Прибавляет единицу счётчику команды; первого вызова задаёт first_seen."""
        if not cmd_id:
            return
        stamp = (when or datetime.now()).isoformat(timespec="seconds")
        with self._lock:
            data = self.snapshot()
            entry = data.get(cmd_id)
            if not isinstance(entry, dict):
                entry = {}
            entry["count"] = _as_int(entry.get("count")) + 1
            entry.setdefault("first_seen", stamp)
            entry["last_seen"] = stamp
            data[cmd_id] = entry
            self._write(data)

    def _write(self, data: dict) -> None:
        """Атомарная перезапись файла (во временный + os.replace)."""
        try:
            folder = os.path.dirname(self._path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2,
                          sort_keys=True)
            os.replace(tmp, self._path)
        except Exception as exc:  # noqa: BLE001 - запись не валит команду
            swallowed(f"command_stats.write({self._path})", exc)


def _as_int(value: object) -> int:
    """Счётчик мог испортиться вручную — считаем только целые, иначе 0."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _load_commands(commands_file: str) -> dict:
    """Команды устройства для отчёта (пустой dict при отсутствии/сбое)."""
    try:
        with open(commands_file, encoding="utf-8") as file:
            data = json.load(file)
    except Exception as exc:  # noqa: BLE001 - отчёт не должен падать на конфиге
        return swallowed(f"command_stats.commands({commands_file})", exc, {})
    return data if isinstance(data, dict) else {}


def known_ids(commands_data: dict) -> set:
    """Исполняемые id commands.json: обычные команды и sequences."""
    ids = set(commands_data.get("commands", {}))
    ids |= set(commands_data.get("sequences", {}))
    return ids


def build_report(commands_file: str) -> list[tuple[int, str, str, str]]:
    """Строки (count, last_seen, id, описание) по возрастанию использования."""
    data = _load_commands(commands_file)
    stats = CommandStats(stats_path_for(commands_file)).snapshot()
    descriptions = data.get("descriptions", {})
    rows: list[tuple[int, str, str, str]] = []
    for cmd_id in known_ids(data):
        entry = stats.get(cmd_id)
        if not isinstance(entry, dict):
            entry = {}
        rows.append((_as_int(entry.get("count")), str(entry.get("last_seen", "")),
                     cmd_id, str(descriptions.get(cmd_id, ""))))
    rows.sort(key=lambda row: (row[0], row[2]))
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: печатает частоту использования команд устройства.

    python -m lib.voice_cmd.command_stats [--commands PATH]
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    _force_utf8_stdout()
    commands_file = _default_commands_file()
    if argv[:1] in (["--commands"], ["-c"]) and len(argv) > 1:
        commands_file = argv[1]
    rows = build_report(commands_file)
    print(f"Статистика команд: {stats_path_for(commands_file)}")
    print(f"{'вызовов':>8}  {'последний':19}  {'id':22} описание")
    never = 0
    for count, last, cmd_id, description in rows:
        never += 1 if count == 0 else 0
        print(f"{count:>8}  {(last or '—'):19}  {cmd_id:22} {description}")
    print(f"\nВсего команд: {len(rows)}, ни разу не использовано: {never}")
    return 0


def _default_commands_file() -> str:
    """commands.json текущего устройства (импорт внутри — ради лёгкого CLI)."""
    import platform

    from lib.voice_cmd.config_loader import get_device_commands_path
    return get_device_commands_path(platform.node())


def _force_utf8_stdout() -> None:
    """Консоль Windows в cp1251 не печатает описания с юникодом (⏹, ё) —
    переключаем stdout в UTF-8; сбой не валяет отчёт."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - только вывод, не данные
        swallowed("command_stats.stdout", exc)


if __name__ == "__main__":
    raise SystemExit(main())
