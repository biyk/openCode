# lib/voice_cmd/knowledge_review.py
"""Доска «проверка знаний»: запуск GUI-сервера (точка входа).

    python -m lib.voice_cmd.knowledge_review launch   # для голосовой команды
    python -m lib.voice_cmd.knowledge_review serve    # сам сервер (detached)
    python -m lib.voice_cmd.knowledge_review status   # жив ли сервер

launch идемпотентен: сервер уже отвечает — просто открываем страницу в
дебаг-браузере (CDP 9222, при закрытом Brave поднимается сам); не
отвечает — поднимаем detached-процесс (лог: logs/review_server.log)
и открываем.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
import urllib.request
from typing import Optional

from lib.voice_cmd.config_loader import get_device_commands_path
from lib.voice_cmd.knowledge_review_recognize import load_review
from lib.voice_cmd.knowledge_review_server import serve

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UP_WAIT_S = 10.0


def commands_file() -> str:
    """commands.json текущего устройства (рядом knowledge/review.json)."""
    return get_device_commands_path(platform.node())


def is_up(port: int) -> bool:
    """Отвечает ли сервер доски на /api/ping."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False  # сервер ещё не поднялся / лежит — штатный ответ пробы


def spawn_server(port: int) -> None:
    """Стартует detached-процесс сервера доски (serve_forever)."""
    log_path = os.path.join(REPO_ROOT, "logs", "review_server.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    cmd = [sys.executable, "-m", "lib.voice_cmd.knowledge_review",
           "serve", "--port", str(port)]
    kwargs: dict = {
        "cwd": REPO_ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": open(log_path, "ab"),
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)  # detached, живёт после нашего exit


def open_page(port: int) -> None:
    """Открывает доску в дебаг-браузере (поднимет Brave, если закрыт)."""
    from lib.browser_control import open_url
    url = f"http://127.0.0.1:{port}/"
    if not open_url(url):
        print(f"[Review] Браузер не открылся — адрес: {url}")


def launch(port: Optional[int] = None) -> int:
    """Поднять сервер (если лежит) и открыть страницу. Для shell-команды."""
    cfile = commands_file()
    use_port = int(port or load_review(cfile).get("port") or 8765)
    if not is_up(use_port):
        print(f"[Review] Запуск сервера доски на :{use_port}...")
        spawn_server(use_port)
        deadline = time.time() + UP_WAIT_S
        while time.time() < deadline and not is_up(use_port):
            time.sleep(0.3)
        if not is_up(use_port):
            print(f"[Review] Сервер не поднялся за {UP_WAIT_S}с "
                  f"(см. logs/review_server.log)")
            return 1
    open_page(use_port)
    print(f"[Review] Доска открыта: http://127.0.0.1:{use_port}/")
    return 0


def main(argv: Optional[list] = None) -> int:
    """CLI: launch (по умолчанию) / serve / serve --port N / status."""
    args = (argv if argv is not None else sys.argv[1:]) or ["launch"]
    port = None
    if "--port" in args:
        i = args.index("--port")
        port = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    cmd = args[0]
    if cmd == "launch":
        return launch(port)
    if cmd == "serve":
        return serve(commands_file(), port)
    if cmd == "status":
        use = port or int(load_review(commands_file()).get("port") or 8765)
        print(f"[Review] {'жив' if is_up(use) else 'НЕ отвечает'} "
              f"на :{use}")
        return 0 if is_up(use) else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
