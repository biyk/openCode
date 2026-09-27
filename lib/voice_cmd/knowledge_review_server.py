# lib/voice_cmd/knowledge_review_server.py
"""HTTP-сервер доски «проверка знаний» (stdlib http.server).

API (JSON, всё на 127.0.0.1):
  GET  /              — HTML-страница с четырьмя вкладками
  GET  /api/ping      — {"ok": true} (проверка «сервер уже жив»)
  GET  /api/board     — корзины + список команд + настройки
  POST /api/act       — confirm/demote/forget/update записи базы знаний
  POST /api/recognize — «попробовать распознать» (Laya → LLM)
  POST /api/scan      — запустить сканирование логов в базу знаний
  GET  /api/scan      — прогресс сканирования {running, done, total, added}
  POST /api/settings  — сохранить port/llm_url/llm_model в review.json

Операции доски (board_snapshot/apply_act/laya_status) — в
knowledge_review_board; здесь только приём запросов и запуск.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from lib.voice_cmd.knowledge import KnowledgeStore
from lib.voice_cmd.knowledge_review_board import (
    apply_act, board_snapshot, laya_status,
)
from lib.voice_cmd.knowledge_review_recognize import (
    load_review, save_review, try_recognize,
)
from lib.voice_cmd.knowledge_review_scan import start as scan_start
from lib.voice_cmd.knowledge_review_scan import status as scan_status
from lib.voice_cmd.knowledge_review_ui import PAGE


class ReviewHandler(BaseHTTPRequestHandler):
    """Раздача страницы и JSON-API; конфигурация инжектируется в __init__."""

    def __init__(self, *args, store: Optional[KnowledgeStore] = None,
                 commands_file: str = "", review: Optional[dict] = None,
                 **kwargs) -> None:
        self.store = store
        self.commands_file = commands_file
        self.review = review or {}
        super().__init__(*args, **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[Review] {self.address_string()} {fmt % args}")

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
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/ping":
            self._json(200, {"ok": True})
        elif self.path == "/api/board":
            assert self.store is not None
            snap = board_snapshot(self.store, self.commands_file, self.review)
            snap["laya"] = laya_status(self.commands_file)
            self._json(200, snap)
        elif self.path == "/api/scan":
            self._json(200, scan_status())
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "bad json"})
            return
        assert self.store is not None
        if self.path == "/api/act":
            self._json(200, {"ok": apply_act(self.store, body)})
        elif self.path == "/api/recognize":
            res = try_recognize(str(body.get("text") or ""),
                                self.commands_file, self.review)
            self._json(200, res)
        elif self.path == "/api/scan":
            self._json(200, {"started": scan_start(
                self.store, self.commands_file)})
        elif self.path == "/api/settings":
            ok = save_review(self.commands_file, body)
            if ok:
                self.review.update(dict(body))
            self._json(200, {"ok": ok})
        else:
            self._json(404, {"error": "not found"})


def make_server(store: KnowledgeStore, commands_file: str, review: dict,
                port: int) -> ThreadingHTTPServer:
    """ThreadingHTTPServer с инжектированными зависимостями (127.0.0.1)."""
    def handler(*args, **kwargs):
        return ReviewHandler(*args, store=store, commands_file=commands_file,
                             review=review, **kwargs)
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(commands_file: str, port: Optional[int] = None) -> int:
    """Запуск сервера доски (блокирующий; вызывается detached-процессом)."""
    review = load_review(commands_file)
    use_port = int(port or review.get("port") or 8765)
    store = KnowledgeStore(
        KnowledgeStore.path_for_commands_file(commands_file))
    httpd = make_server(store, commands_file, review, use_port)
    print(f"[Review] Доска знаний: http://127.0.0.1:{use_port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
