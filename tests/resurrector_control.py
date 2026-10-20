"""Управление приложением через конфиг resurrector (для тестов).

Тест main.py должен запускаться, когда само приложение не крутится
параллельно. Помощник выключает запись ['Voice Control'] в конфиге
resurrector (атомарной записью — так требует fsnotify resurrector),
дожидается остановки процесса и умеет вернуть всё как было.
"""
from __future__ import annotations

import os
import subprocess
import time

from contextlib import contextmanager
from pathlib import Path

CONFIG_PATH = (
    Path(os.path.expanduser("~")) / ".config" / "resurrector" / "config.toml"
)
_SECTION = "voice control"


def _read_lines() -> list:
    return CONFIG_PATH.read_text(encoding="utf-8").splitlines(keepends=True)


def _section_bounds(lines: list):
    """Границы секции ['Voice Control'] в списке строк."""
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("[") and _SECTION in ln.lower():
            start = i
            break
    if start is None:
        return None, None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip().startswith("["):
            end = j
            break
    return start, end


def get_enabled():
    """Текущее enabled приложения или None, если секции/файла нет."""
    if not CONFIG_PATH.exists():
        return None
    lines = _read_lines()
    start, end = _section_bounds(lines)
    if start is None:
        return None
    for ln in lines[start + 1:end]:
        s = ln.strip()
        if s.startswith("enabled"):
            return "true" in s.lower()
    return True


def _write_atomic(lines: list) -> None:
    tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


def set_enabled(enabled: bool) -> bool:
    """Атомарно выставляет enabled у приложения. False — если файла нет."""
    if not CONFIG_PATH.exists():
        return False
    lines = _read_lines()
    start, end = _section_bounds(lines)
    if start is None:
        return False
    val = "true" if enabled else "false"
    for i in range(start + 1, end):
        if lines[i].strip().startswith("enabled"):
            lines[i] = "enabled = %s\n" % val
            _write_atomic(lines)
            return True
    insert_at = end
    for i in range(start + 1, end):
        if lines[i].strip().startswith("cwd"):
            insert_at = i + 1
            break
    lines.insert(insert_at, "enabled = %s\n" % val)
    _write_atomic(lines)
    return True


def _main_app_pids():
    """PID python-процессов с main.py или None, если определить не вышло."""
    try:
        proc = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            capture_output=True, timeout=15)
    except Exception:
        return None
    # wmic печатает системной кодировкой (cp866/cp1251), поэтому читаем байты:
    # `text=True` без `encoding` под `-X utf8` не декодирует вывод и кладёт
    # в stdout None — а `None.splitlines()` ронял всю тестовую сессию. Пустой
    # вывод остаётся «определить не вышло»: пустой список здесь означал бы
    # «приложения нет», и живые тесты пошли бы поверх всё ещё живого процесса.
    if proc.stdout is None:
        return None
    # Идентификатор процесса и «main.py» — ASCII, они переживают замену.
    out = proc.stdout.decode("utf-8", errors="replace")
    pids = []
    for line in out.splitlines():
        if "main.py" not in line:
            continue
        last = line.rsplit(",", 1)[-1].strip()
        if last.isdigit():
            pids.append(int(last))
    return pids


def wait_app_stopped(timeout: float = 15.0) -> bool:
    """Ждёт остановки приложения. True — остановлено (или уже не было)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pids = _main_app_pids()
        if pids is not None and not pids:
            return True
        time.sleep(1.0)
    return False


@contextmanager
def paused_app():
    """Гасит приложение на время live-сессии и включает его ОБЯЗАТЕЛЬНО.

    Выключение и ожидание стоят ВНУТРИ try: падение на любом из шагов
    обязано вернуть enabled=True. Если бы `set_enabled(False)` выполнялся до
    try (как раньше), упавшая проверка процессов оставляла ассистента
    выключенным намертво — и живым его не считал бы даже следующий прогон,
    потому что он запомнил бы уже выключенное состояние как «исходное».

    Не трогает ничего, если приложение было выключено ДО нас (False) или
    секции/файла нет (None): «восстановить False» — это не восстановить,
    а оставить пользователя без ассистента.
    """
    original = get_enabled()
    if original is not True:
        yield False
        return
    try:
        set_enabled(False)
        wait_app_stopped()
        yield True
    finally:
        set_enabled(original)
