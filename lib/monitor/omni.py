# TOOLTIP: OmniRouter: проба здоровья и подъём/перезапуск его собственным CLI
"""OmniRouter как внешний процесс: проверка живости и команда перезапуска.

Процесс чужой (npm-пакет `omniroute`, `node …/bin/omniroute.mjs`), поэтому
чиним его средствами самого CLI: `stop` снимает процесс по pid-файлу
(или kill по порту, если файл потерялся), `serve --daemon` стартует detached
сервером. `restart --daemon` непригоден: у команды restart нет такой опции
(Commander падает с «unknown option»), а без неё сервер стартует в foreground
того же процесса. Сам убивать процессы не будем: в `node.exe` на этом ПК
живёт редактор.
"""
import os
import shutil
import socket
import subprocess
import time
from typing import Optional
from urllib.parse import urlparse

from lib.monitor.probes import http_ok
from lib.monitor.tuning import (MONITOR_OMNI_HEALTH_PATH,
                                MONITOR_OMNI_HEALTH_TIMEOUT_S,
                                MONITOR_OMNI_PORT,
                                MONITOR_OMNI_STOP_TIMEOUT_S,
                                MONITOR_OMNI_URL, MONITOR_OMNI_UP_WAIT_S,
                                MONITOR_OMNI_RESTART_TIMEOUT_S,
                                MONITOR_PROBE_TIMEOUT_S)

# npm кладёт шим (`omniroute.cmd`) рядом с node_modules пакета.
ENTRY = os.path.join("node_modules", "omniroute", "bin", "omniroute.mjs")


def port_from_url(base_url: str = MONITOR_OMNI_URL) -> int:
    """Порт из адреса прокси; без порта в URL — дефолтный MONITOR_OMNI_PORT."""
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    return int(parsed.port or MONITOR_OMNI_PORT)


def is_healthy(base_url: str = MONITOR_OMNI_URL,
               timeout: float = MONITOR_OMNI_HEALTH_TIMEOUT_S) -> bool:
    """Отвечает ли `/api/health` (2xx): прокси жив и разговаривает."""
    url = base_url.rstrip("/") + MONITOR_OMNI_HEALTH_PATH
    return http_ok(url, timeout)


def is_listening(base_url: str = MONITOR_OMNI_URL,
                 timeout: float = MONITOR_PROBE_TIMEOUT_S) -> bool:
    """Открыт ли порт: отличает «процесс мёртв» от «висит, не отвечает»."""
    host = urlparse(base_url).hostname or "127.0.0.1"
    try:
        with socket.create_connection((host, port_from_url(base_url)),
                                      timeout=timeout):
            return True
    except OSError:
        return False  # порт закрыт — штатный ответ пробы, не ошибка


def entry_path() -> Optional[str]:
    """Путь к bin/omniroute.mjs рядом с npm-шимом; None — пакета нет в PATH."""
    shim = shutil.which("omniroute")
    if not shim:
        return None
    mjs = os.path.join(os.path.dirname(shim), ENTRY)
    return mjs if os.path.exists(mjs) else None


def cli_argv(args: list) -> Optional[list]:
    """Команда CLI: `node …/omniroute.mjs <args>`; иначе — шим через cmd.exe.

    .cmd-шим напрямую CreateProcess не запускается, поэтому запасной путь
    идёт через `cmd.exe /d /c` (args передаются отдельными аргументами).
    """
    node = shutil.which("node")
    mjs = entry_path()
    if node and mjs:
        return [node, mjs] + list(args)
    shim = shutil.which("omniroute")
    if not shim:
        return None
    return ["cmd.exe", "/d", "/c", shim] + list(args)


def _run_cli(args: list, timeout_s: float) -> tuple:
    """Один вызов CLI. Возвращает (rc, последние строки вывода).

    rc is None — CLI вообще не найден или запуск не удался: это причина в
    тексте, а не исключение (смотритель должен показать её, а не упасть).
    """
    argv = cli_argv(args)
    if argv is None:
        return None, "CLI omniroute не найден (npm install -g omniroute)"
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout_s, encoding="utf-8",
                              errors="replace")
    except subprocess.TimeoutExpired:
        return None, f"CLI «{args[0]}» не завершился за {timeout_s:.0f} с"
    except OSError as error:
        return None, f"сбой запуска CLI: {type(error).__name__}"
    lines = [ln.strip() for ln in ((proc.stdout or "") + "\n" +
                                   (proc.stderr or "")).splitlines()
             if ln.strip()]
    tail = lines[-1][:120] if lines else "CLI молчал"
    return proc.returncode, tail


def _wait_port(url: str, wait_s: float, poll_s: float = 1.0) -> bool:
    """Ждёт открытого порта: spawn ещё не значит «сервер слушает»."""
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if is_listening(url):
            return True
        time.sleep(poll_s)
    return is_listening(url)


def restart(port: Optional[int] = None,
            timeout_s: float = MONITOR_OMNI_RESTART_TIMEOUT_S,
            stop_timeout_s: float = MONITOR_OMNI_STOP_TIMEOUT_S,
            up_wait_s: float = MONITOR_OMNI_UP_WAIT_S) -> tuple:
    """Поднять/перезапустить собственным CLI: `stop` + `serve --daemon`.

    `omniroute restart --daemon` не существует: у restart только --port, и
    Commander отсекает неизвестную опцию (rc=1, «error: unknown option»),
    а без --daemon restart вызывает runServe в foreground того же процесса —
    такой CLI никогда не вернулся бы. Отсоединённый сервер умеет только
    `serve --daemon` (spawn detached + pid-файл), поэтому порядок такой:
    `stop` (убить зависший, если он ещё держит порт; осечка не помеха —
    процесс мог упасть сам) и `serve --daemon --port N`.

    Возвращает (ok, подробности для GUI); ok=True — только когда порт
    действительно открылся.
    """
    use = int(port if port is not None
              else port_from_url(MONITOR_OMNI_URL))
    url = f"http://127.0.0.1:{use}"
    rc, tail = _run_cli(["stop"], stop_timeout_s)
    if rc is None:
        return False, tail
    rc, tail = _run_cli(["serve", "--daemon", "--port", str(use)], timeout_s)
    if rc != 0:
        return False, f"порт :{use} · CLI не поднял сервер: {tail}"
    if not _wait_port(url, up_wait_s):
        return False, (f"порт :{use} · CLI запустил сервер, но порт "
                       f"не открылся за {up_wait_s:.0f} с")
    return True, f"порт :{use} · {tail}"


__all__ = ["cli_argv", "entry_path", "is_healthy", "is_listening",
           "port_from_url", "restart"]
