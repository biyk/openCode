# lib/voice_cmd/knowledge_review_scan.py
"""Сканер логов для доски знаний (кнопка «сканировать»).

Идёт по logs/*.log, вытаскивает [TEXT]-строки с триггерами («алиса»,
«пожалуйста») и проверяет каждую фразу детектором: совпадение в
commands.json → Лайя. Распознанная фраза игнорируется, нераспознанная
кладётся в knowledge.json (корзина undefined) — так наполняется база.
Каждый ЗАВЕРШЁННЫЙ лог архивируется в logs/zip/YYYYMMDD.zip (дата из имени
файла) и удаляется. Живой лог (менялся меньше ACTIVE_S назад) сканируется
ХВОСТОМ — последние ACTIVE_TAIL_LINES строк — и остаётся на месте: в него
пишет воркер. Скан стартует сам при открытии/обновлении страницы доски —
иначе он ждал бы паузы воркера в ACTIVE_S секунд и не видел бы свежие фразы.

run_scan — синхронный; start() поднимает его в daemon-потоке,
status() отдаёт прогресс (POST/GET /api/scan на доске).
"""

from __future__ import annotations

import os
import re
import threading
import time
import zipfile
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge import BUCKETS, UNDEFINED, KnowledgeStore

ACTIVE_S = 300
ACTIVE_TAIL_LINES = 500
_TEXT_RE = re.compile(r"\[TEXT\] (.*)$")
_DATE_RE = re.compile(r"(\d{8})")

_LOCK = threading.Lock()
_STATE: dict = {"running": False, "total": 0, "done": 0, "phrases": 0,
                "added": 0, "archived": 0, "errors": 0}


def logs_dir_for(commands_file: str) -> str:
    """logs/ в корне репозитория (commands_file — targets/<host>/…)."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(commands_file)))
    return os.path.join(root, "logs")


class Checker:
    """Детектор по умолчанию: матчер commands.json, затем Лайя (если жива)."""

    def __init__(self, commands_file: str) -> None:
        from lib.voice_cmd.commands import CommandMatcher
        from lib.voice_cmd.knowledge_review_levels import laya_guess
        self._matcher = CommandMatcher(commands_file)
        self._laya = laya_guess
        self._commands_file = commands_file

    def has_trigger(self, text: str) -> bool:
        return self._matcher.has_trigger(text)

    def core(self, text: str) -> str:
        return self._matcher.core_phrase(text)

    def recognized(self, text: str) -> bool:
        if self._matcher.find_command(text)[0] is not None:
            return True
        return self._laya(text, self._commands_file) is not None


def _phrases(path: str, checker, tail: int = 0) -> list[tuple[str, str]]:
    """(исходная строка, ядро без триггеров) для [TEXT]-строк с триггером.

    tail>0 — только последние N строк: живой лог дописывается воркером,
    прогонять его целиком дорого (на каждую нераспознанную фразу — ход к
    Лайе), а старые строки этого же файла сканировались в прошлый раз.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    if 0 < tail < len(lines):
        lines = lines[-tail:]
    out: list[tuple[str, str]] = []
    for line in lines:
        m = _TEXT_RE.search(line.rstrip())
        if not m:
            continue
        raw = m.group(1).strip()
        if not raw or not checker.has_trigger(raw):
            continue
        core = checker.core(raw)
        if core:
            out.append((raw, core))
    return out


def _archive(logs_dir: str, path: str) -> None:
    """Перекладывает лог в logs/zip/<дата>.zip и удаляет оригинал."""
    name = os.path.basename(path)
    m = _DATE_RE.search(name)
    day = m.group(1) if m else time.strftime(
        "%Y%m%d", time.localtime(os.path.getmtime(path)))
    zpath = os.path.join(logs_dir, "zip", day + ".zip")
    os.makedirs(os.path.dirname(zpath), exist_ok=True)
    with zipfile.ZipFile(zpath, "a", zipfile.ZIP_DEFLATED) as z:
        if name not in z.namelist():
            z.write(path, name)
    os.remove(path)


def _stale(path: str) -> bool:
    """True, если файл не менялся ACTIVE_S секунд (законченная сессия)."""
    try:
        return time.time() - os.path.getmtime(path) >= ACTIVE_S
    except OSError:
        return False


def _targets(logs_dir: str) -> list[tuple[str, bool]]:
    """[(путь, завершённый_ли)]: живой лог идёт первым и не архивируется."""
    try:
        names = sorted(n for n in os.listdir(logs_dir) if n.endswith(".log"))
    except OSError as e:
        swallowed("review.scan_dir", e)
        return []
    paths = [os.path.join(logs_dir, n) for n in names]
    live = [p for p in paths if not _stale(p)]
    done = [p for p in paths if _stale(p)]
    return [(p, False) for p in live] + [(p, True) for p in done]


def run_scan(store: KnowledgeStore, commands_file: str,
             logs_dir: Optional[str] = None, checker=None) -> dict:
    """Сканирует логи: нераспознанное → undefined, завершённые — в архив.

    Живой (пишущийся сейчас) лог берётся хвостом и не трогается — иначе
    авто-скан при открытии доски не находил бы ничего.
    """
    logs_dir = logs_dir or logs_dir_for(commands_file)
    checker = checker or Checker(commands_file)
    targets = _targets(logs_dir)
    known: set[str] = set()
    for bucket in BUCKETS:
        known.update(store.entries(bucket))
    summary = {"total": len(targets), "done": 0, "phrases": 0, "added": 0,
               "archived": 0, "errors": 0}
    with _LOCK:
        _STATE.update(summary, running=True)
    for path, finished in targets:
        try:
            for raw, core in _phrases(
                    path, checker, 0 if finished else ACTIVE_TAIL_LINES):
                summary["phrases"] += 1
                if core in known or checker.recognized(raw):
                    continue  # уже в базе / распознано детектором — игнор
                known.add(core)
                if store.record(UNDEFINED, core):
                    summary["added"] += 1
            if finished:
                _archive(logs_dir, path)
                summary["archived"] += 1
        except Exception as e:
            swallowed("review.scan_log", e)
            summary["errors"] += 1
        summary["done"] += 1
        with _LOCK:
            _STATE.update(summary, running=True)
    with _LOCK:
        _STATE.update(summary, running=False)
    return summary


def start(store: KnowledgeStore, commands_file: str, logs_dir: str = "",
          checker=None) -> bool:
    """Запускает скан в daemon-потоке; False, если скан уже идёт."""
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE.update(running=True, total=0, done=0, phrases=0, added=0,
                      archived=0, errors=0)  # не ждём запуска потока
    threading.Thread(target=run_scan, daemon=True,
                     args=(store, commands_file, logs_dir or None,
                           checker)).start()
    return True


def status() -> dict:
    """Копия прогресса текущего/последнего скана."""
    with _LOCK:
        return dict(_STATE)
