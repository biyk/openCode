# lib/voice_cmd/knowledge_review_server.py
"""HTTP-сервер доски «проверка знаний» (stdlib http.server).

API (JSON, всё на 127.0.0.1):
  GET  /              — HTML-страница с пятью вкладками
  GET  /api/ping      — {"ok": true} (проверка «сервер уже жив»)
  GET  /api/board     — корзины + список команд + настройки + статистика
  GET  /api/tasks     — названия задач real_life_tasks (подсказка task-complete)
  POST /api/act       — confirm/demote/forget/update/purge записи базы знаний
                        (purge снимает confirmed-фразу из match в commands.json;
                        если match-записи нет — forget из базы знаний)
  POST /api/recognize — «попробовать распознать» (commands.json → Laya → LLM)
  POST /api/recognize_all — массовый прогон undefined-корзины
  GET  /api/recognize_all — прогресс {running, done, total, recognized}
  GET  /api/recognize_log — след последнего прогона {log, running, total, done}
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
    apply_act, board_snapshot, delete_confirmed_phrase, laya_status,
    sheet_task_titles,
)
from lib.voice_cmd.knowledge_review_bulk import log_text as bulk_log
from lib.voice_cmd.knowledge_review_bulk import start as bulk_start
from lib.voice_cmd.knowledge_review_bulk import status as bulk_status
from lib.voice_cmd.knowledge_review_detect import try_recognize
from lib.voice_cmd.knowledge_review_recognize import load_review, save_review
from lib.voice_cmd.knowledge_review_scan import start as scan_start
from lib.voice_cmd.knowledge_review_scan import status as scan_status
from lib.voice_cmd.knowledge_review_stats import stats_html
from lib.voice_cmd.knowledge_review_ui_log import page


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
            html = page().encode("utf-8")
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/ping":
            self._json(200, {"ok": True})
        elif self.path == "/api/board":
            assert self.store is not None
            snap = board_snapshot(self.store, self.commands_file, self.review)
            snap["laya"] = laya_status(self.commands_file)
            snap["stats"] = stats_html(self.commands_file)
            self._json(200, snap)
        elif self.path == "/api/tasks":
            # Отдельно от /api/board: чтение Sheets дорогое и может
            # потребовать ре-авторизации — оно нужно только для task-complete.
            self._json(200, {"tasks": sheet_task_titles()})
        elif self.path == "/api/scan":
            self._json(200, scan_status())
        elif self.path == "/api/recognize_all":
            self._json(200, bulk_status())
        elif self.path == "/api/recognize_log":
            # След последнего прогона: он же показывает, что идёт сейчас.
            # Статус читается защитно — попап не должен падать из-за того,
            # что ключа в прогрессе нет.
            st = bulk_status()
            self._json(200, {"log": bulk_log(),
                             "running": bool(st.get("running")),
                             "total": int(st.get("total") or 0),
                             "done": int(st.get("done") or 0)})
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
            if str(body.get("action") or "") == "purge":
                res = delete_confirmed_phrase(
                    self.store, self.commands_file,
                    str(body.get("text") or ""))
                self._json(200, {"ok": bool(res["match"] or res.get("knowledge")),
                                 **res})
            else:
                self._json(200, {"ok": apply_act(
                    self.store, body, self.commands_file)})
        elif self.path == "/api/recognize":
            res = try_recognize(str(body.get("text") or ""),
                                self.commands_file, self.review)
            self._json(200, res)
        elif self.path == "/api/recognize_all":
            self._json(200, {"started": bulk_start(
                self.store, self.commands_file, self.review)})
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
