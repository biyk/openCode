# lib/voice_cmd/knowledge_review_bulk.py
"""Массовое распознавание корзины «не распознано»: все фразы по очереди.

Для каждой undefined-записи вызывается try_recognize (Лайя → LLM). Если
распознавание удалось, фраза переезжает в корзину laya (вкладка «Лайя» —
очередь на досмотр: там она ждёт ручного подтверждения → confirmed).
Записи со старой догадкой, вписанной в undefined прежним кодом
(command/event уже заполнены), переезжают в laya без повторного опроса.
Прогресс отдаёт status(); start() гоняет в daemon-потоке и не даёт
запускать второй прогон распознавания одновременно.
"""

from __future__ import annotations

import threading
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge import (
    COMMAND, LAYA, UNDEFINED, KnowledgeStore,
)
from lib.voice_cmd.knowledge_review_recognize import try_recognize

GUESS_KINDS = ("command", "start", "finish")

_LOCK = threading.Lock()
_STATE: dict = {"running": False, "total": 0, "done": 0,
                "recognized": 0, "current": ""}


def _carried_guess(entry: dict) -> Optional[dict]:
    """Догадка, уже вписанная в запись старым прогоном (command/event в
    undefined), — переезжает в laya без повторного опроса ИИ."""
    if entry.get("command") or entry.get("event"):
        return {"via": "carry", "kind": entry.get("kind", COMMAND),
                "command": entry.get("command", ""),
                "event": entry.get("event", "")}
    return None


def run_all(store: KnowledgeStore, commands_file: str,
            review: dict) -> dict:
    """Синхронный прогон всей корзины undefined; возвращает итог."""
    snapshot = store.entries(UNDEFINED)
    texts = sorted(snapshot)
    summary = {"total": len(texts), "done": 0, "recognized": 0}
    with _LOCK:
        _STATE.update(summary, running=True, current="")
    for text in texts:
        with _LOCK:
            _STATE["current"] = text
        guess = _carried_guess(snapshot[text])
        if guess is None:
            try:
                guess = try_recognize(text, commands_file, review)
            except Exception as e:
                swallowed("review.bulk_recognize", e)
                guess = {"via": "none"}
        if (guess.get("via", "none") != "none"
                and guess.get("kind") in GUESS_KINDS
                and store.record(LAYA, text, guess["kind"],
                                 command=guess.get("command") or None,
                                 event=guess.get("event") or None)):
            summary["recognized"] += 1
        summary["done"] += 1
        with _LOCK:
            _STATE.update(summary, running=True)
    with _LOCK:
        _STATE.update(summary, running=False, current="")
    return summary


def start(store: KnowledgeStore, commands_file: str, review: dict) -> bool:
    """Запуск в daemon-потоке; False, если прогон уже идёт."""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE.update(running=True, total=0, done=0, recognized=0,
                      current="")
    threading.Thread(target=run_all, daemon=True,
                     args=(store, commands_file, review)).start()
    return True


def status() -> dict:
    """Копия прогресса текущего/последнего прогона."""
    with _LOCK:
        return dict(_STATE)
