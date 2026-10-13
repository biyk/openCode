# lib/monitor/dashboard.py
"""Дашборд «что сейчас живёт»: detached HTTP-сервер + app-окно браузера.

    python -m lib.monitor.dashboard launch   # поднять сервер и открыть окно
    python -m lib.monitor.dashboard serve    # сам сервер (detached-процесс)
    python -m lib.monitor.dashboard status   # жив ли сервер

Сервер НЕ в основном процессе: не тормозит main и красит всё, если main
завис. Читает heartbeat-файл + сам пробабит порты (см. status.collect).
API:  GET / — страница, GET /api/ping — {ok:true}, GET /api/status — список.
Точка входа и идемпотентный запуск повторяют паттерн knowledge_review.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from lib.monitor.status import collect
from lib.monitor.tuning import MONITOR_PORT
from lib.monitor.ui import page

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UP_WAIT_S = 10.0


class MonitorHandler(BaseHTTPRequestHandler):
    """Раздача страницы и /api/status (всё только на 127.0.0.1)."""

    def log_message(self, fmt: str, *args) -> None:
        print(f"[Monitor] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if self.path == "/":
            self._send(200, page().encode("utf-8"),
                       "text/html; charset=utf-8")
        elif self.path == "/api/ping":
            self._json(200, {"ok": True})
        elif self.path == "/api/status":
            self._json(200, collect())
        else:
            self._json(404, {"error": "not found"})


def make_server(port: int) -> ThreadingHTTPServer:
    """ThreadingHTTPServer на 127.0.0.1 (раздача статуса и страницы)."""
    return ThreadingHTTPServer(("127.0.0.1", port), MonitorHandler)


def is_up(port: int) -> bool:
    """Отвечает ли дашборд на /api/ping."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def spawn_server(port: int) -> None:
    """Стартует detached-процесс сервера (живёт после нашего exit)."""
    log_path = os.path.join(REPO_ROOT, "logs", "monitor_server.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    cmd = [sys.executable, "-m", "lib.monitor.dashboard", "serve",
           "--port", str(port)]
    kwargs: dict = {
        "cwd": REPO_ROOT, "stdin": subprocess.DEVNULL,
        "stdout": open(log_path, "ab"), "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def open_page(port: int) -> None:
    """Открывает дашборд в дебаг-браузере (поднимет его, если закрыт)."""
    from lib.browser_control import open_url
    url = f"http://127.0.0.1:{port}/"
    if not open_url(url):
        print(f"[Monitor] Браузер не открылся — адрес: {url}")


def launch(port: Optional[int] = None, output=None) -> int:
    """Поднять сервер (если лежит) и открыть app-окно. Идемпотентно."""
    use_port = int(port or MONITOR_PORT)
    say = (output.print_info if output is not None else print)
    if not is_up(use_port):
        say(f"[Monitor] Запуск дашборда на :{use_port}...")
        spawn_server(use_port)
        deadline = time.time() + UP_WAIT_S
        while time.time() < deadline and not is_up(use_port):
            time.sleep(0.3)
        if not is_up(use_port):
            say(f"[Monitor] Не поднялся за {UP_WAIT_S}с "
                f"(см. logs/monitor_server.log)")
            return 1
    open_page(use_port)
    say(f"[Monitor] Открыто: http://127.0.0.1:{use_port}/")
    return 0


def serve(port: Optional[int] = None) -> int:
    """Запуск сервера (блокирующий; вызывается detached-процессом)."""
    use_port = int(port or MONITOR_PORT)
    httpd = make_server(use_port)
    print(f"[Monitor] Дашборд: http://127.0.0.1:{use_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def main(argv: Optional[list] = None) -> int:
    """CLI: launch (по умолчанию) / serve / status; опция --port N."""
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
        return serve(port)
    if cmd == "status":
        use = port or MONITOR_PORT
        print(f"[Monitor] {'жив' if is_up(use) else 'НЕ отвечает'} :{use}")
        return 0 if is_up(use) else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
