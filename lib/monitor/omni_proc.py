# TOOLTIP: Процесс OmniRouter снаружи: pid-файл, живость, сколько запросов идёт
"""Взгляд на чужой процесс без права им командовать.

Смотрителю нужно различать состояния, которые одной пробой порта не разделить:

  процесс завершился сам       → поднимать можно и нужно;
  процесс жив, но не отвечает  → кандидат на «завис», но убивать нельзя, если
                                 он прямо сейчас обслуживает запрос;
  проверить нечем              → ничего разрушительного: destructive-действие
                                 только по доказанному факту.

Отсюда две дешёвые проверки, не требующие авторизации в шлюзе: pid-файл самого
OmniRouter (`~/.omniroute/server/.pid`, его пишет `serve --daemon`) и число
входящих соединений на его порту по TCP-таблице. Замер живьём: в покое
соединений 0, во время одного auto/smart-запроса — 1–2, и ровно в те же
секунды `/healthz` молчал по 10 с. То есть «занят» отделяется от «завис» без
ключей и без токена (у `POST /api/shutdown` — 401).
"""
import ctypes
import subprocess
from pathlib import Path
from typing import Optional

from lib.core.errors import swallowed
from lib.runtime import win_com as w

# Домашняя папка данных OmniRouter: `server/.pid` пишет serve --daemon,
# `supervisor/.pid` — его собственный foreground-надсмотрщик (мы им не владеем).
DATA_DIR = Path.home() / ".omniroute"

STILL_ACTIVE = 259               # GetExitCodeProcess: процесс ещё не завершился
PROCESS_QUERY_LIMITED = 0x1010   # QUERY_LIMITED_INFORMATION


def pid_file(name: str = "server") -> Path:
    """Файл с pid демона (`~/.omniroute/<name>/.pid`)."""
    return DATA_DIR / name / ".pid"


def file_pid(name: str = "server") -> Optional[int]:
    """Pid из файла; None — файла нет или он не читается как число."""
    try:
        raw = pid_file(name).read_text(encoding="utf-8", errors="replace")
        return int(raw.splitlines()[-1].strip())
    except (OSError, IndexError, ValueError):
        return None  # демона нет/файл мусор — штатный ответ пробы, не ошибка


def pid_alive(pid: int) -> Optional[bool]:
    """Жив ли процесс; None — проверить нечем (не Windows или kernel32 отказал)."""
    if w.WINDLL is None or pid <= 0:
        return None
    k32 = w.WINDLL.kernel32
    try:
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
        if not handle:
            return False          # OpenProcess отказал — процесса нет
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    except Exception as error:            # проверка не должна ронять такт
        swallowed("monitor.omni_proc.pid_alive", error)
        return None


def server_running() -> Optional[bool]:
    """Жив ли демон, записанный в pid-файл (None — не проверили)."""
    pid = file_pid()
    if pid is None:
        return False        # файла нет: поднимать нечего, это не «висяк»
    return pid_alive(pid)


def active_connections(port: int) -> Optional[int]:
    """Сколько входящих соединений держит порт (0 = шлюз простаивает).

    None — посчитать нечем (netstat отсутствует или упал, не Windows). Врать
    тут нельзя: прочитай смотритель «ноль» вместо «не знаем», он убьёт занятый
    процесс ровно посреди стрима.
    """
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, text=True, timeout=10,
                             encoding="utf-8", errors="replace").stdout
    except Exception as error:                # нет утилиты — пусть решает репорт
        swallowed("monitor.omni_proc.active_connections", error)
        return None
    found = 0
    want = str(port)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] != "TCP" or parts[3] != "ESTABLISHED":
            continue
        if parts[1].rsplit(":", 1)[-1] == want:
            found += 1
    return found


__all__ = ["active_connections", "file_pid", "pid_alive", "pid_file",
           "server_running"]
