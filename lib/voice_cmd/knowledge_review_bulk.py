# lib/voice_cmd/knowledge_review_bulk.py
"""Массовое распознавание корзины «не распознано»: все фразы по очереди.

Для каждой undefined-записи вызывается try_recognize (фазы — в
knowledge_review_detect). Распознанная фраза переезжает в корзину laya
(вкладка «Лайя» — очередь на досмотр: там она ждёт ручного подтверждения →
confirmed). Записи со старой догадкой, вписанной в undefined прежним кодом
(command/event уже заполнены), переезжают в laya без повторного опроса.
Прогресс отдаёт status(); start() гоняет в daemon-потоке и не даёт запускать
второй прогон одновременно.

Каждая фраза оставляет след (фазы, оценки, причины пропусков) — его собирает
`log_text()`, его же показывает ссылка «логи» на вкладке «Сервер». Журнал
живёт в памяти доски: это последний прогон, на диск ничего не пишется.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd import knowledge_review_trace as kt
from lib.voice_cmd.knowledge import (
    COMMAND, LAYA, UNDEFINED, KnowledgeStore,
)
from lib.voice_cmd.knowledge_review_board import sheet_task_titles
from lib.voice_cmd.knowledge_review_detect import try_recognize

GUESS_KINDS = ("command", "start", "finish")

_LOCK = threading.Lock()
_STATE: dict = {"running": False, "total": 0, "done": 0,
                "recognized": 0, "current": "", "log": ""}


def _carried_guess(entry: dict) -> Optional[dict]:
    """Догадка, уже вписанная в запись старым прогоном (command/event в
    undefined), — переезжает в laya без повторного опроса ИИ."""
    if entry.get("command") or entry.get("event"):
        return {"via": "carry", "kind": entry.get("kind", COMMAND),
                "command": entry.get("command", ""),
                "event": entry.get("event", "")}
    return None


def _carry_trace(text: str, guess: dict) -> str:
    """След перенесённой догадки: ИИ не спрашивали — в логе это видно."""
    tr = kt.Trace(text)
    tr.phase("1\tготовая догадка (фаза 1 и 2 не опрашивались)")
    tr.skipped("commands.json", "догадка уже вписана в базу знаний")
    tr.skipped("Laya", "догадка уже вписана в базу знаний")
    tr.skipped("LLM", "догадка уже вписана в базу знаний")
    tr.result(guess.get("command", ""), "", guess.get("event", ""))
    return tr.text()


def _phrase(text: str, commands_file: str, review: dict,
            titles: list[str]) -> dict:
    """Одна фраза; сбой уровня не роняет прогон — след остаётся."""
    try:
        return try_recognize(text, commands_file, review, titles)
    except Exception as e:
        swallowed("review.bulk_recognize", e)
        return {"via": "none", "kind": "none", "command": "", "event": "",
                "trace": f"фраза:\t{text}\nошибка: {e}"}


def run_all(store: KnowledgeStore, commands_file: str,
            review: dict) -> dict:
    """Синхронный прогон всей корзины undefined; возвращает итог.

    Корзина берётся одним снимком на старт: фразы, наговорённые во время
    прогона, дождутся следующего — иначе очередь никогда не иссяхнет.
    """
    snapshot = store.entries(UNDEFINED)
    texts = sorted(snapshot)
    summary = {"total": len(texts), "done": 0, "recognized": 0}
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    body: list[str] = []
    # Один список задач на прогон: Sheets читается дорого, а в фазе 2 он
    # нужен почти каждой фразе.
    titles = sheet_task_titles() if texts else []
    _publish(stamp, summary, body, running=True)
    for text in texts:
        guess = _carried_guess(snapshot[text])
        if guess is None:
            guess = _phrase(text, commands_file, review, titles)
            body.append(guess.get("trace") or "")
        else:
            body.append(_carry_trace(text, guess))
        if (guess.get("via", "none") != "none"
                and guess.get("kind") in GUESS_KINDS
                and store.record(LAYA, text, guess["kind"],
                                 command=guess.get("command") or None,
                                 event=guess.get("event") or None)):
            summary["recognized"] += 1
        summary["done"] += 1
        _publish(stamp, summary, body, running=True, current=text)
    _publish(stamp, summary, body, running=False)
    return summary


def _publish(stamp: str, summary: dict, body: list[str], running: bool,
             current: str = "") -> None:
    """Прогресс + журнал прогона под одним замком (отдаёт GET status)."""
    header = kt.run_header(stamp, summary["total"], summary["recognized"])
    log = "\n\n".join([header] + [b for b in body if b])
    with _LOCK:
        _STATE.update(summary, running=running, current=current, log=log)


def start(store: KnowledgeStore, commands_file: str, review: dict) -> bool:
    """Запуск в daemon-потоке; False, если прогон уже идёт."""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE.update(running=True, total=0, done=0, recognized=0,
                      current="", log="")
    threading.Thread(target=run_all, daemon=True,
                     args=(store, commands_file, review)).start()
    return True


def status() -> dict:
    """Копия прогресса текущего/последнего прогона (журнал — в log_text)."""
    with _LOCK:
        return dict(_STATE)


def log_text() -> str:
    """След последнего прогона (пусто, если прогонов ещё не было)."""
    with _LOCK:
        return str(_STATE.get("log") or "")
