# lib/voice_cmd/knowledge_review_scan.py
"""Сканер логов для доски знаний (кнопка «сканировать»).

Идёт по logs/*.log, вытаскивает [TEXT]-строки с триггерами («алиса»,
«пожалуйста») и проверяет каждую фразу детектором: совпадение в
commands.json → Лайя. Распознанная фраза игнорируется, нераспознанная
кладётся в knowledge.json (корзина undefined) — так наполняется база.
Каждый просканированный лог архивируется в logs/zip/YYYYMMDD.zip
(дата из имени файла) и удаляется. Свежие логи (меньше ACTIVE_S назад)
не трогаем — в них пишет живой воркер.

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
        from lib.voice_cmd.knowledge_review_recognize import laya_guess
        self._matcher = CommandMatcher(commands_file)
        self._laya = laya_guess
        self._commands_file = commands_file

    def has_trigger(self, text: str) -> bool:
        return self._matcher.has_trigger(text)

    def core(self, text: str) -> str:
        return self._matcher.core_phrase(text)

    def recognized(self, text: str) -> bool:
        if self._matcher.find_command([text])[0] is not None:
            return True
        return self._laya(text, self._commands_file) is not None


def _phrases(path: str, checker) -> list[tuple[str, str]]:
    """(исходная строка, ядро без триггеров) для [TEXT]-строк с триггером."""
    out: list[tuple[str, str]] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
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


def run_scan(store: KnowledgeStore, commands_file: str,
             logs_dir: Optional[str] = None, checker=None) -> dict:
    """Сканирует готовые логи: нераспознанные фразы → undefined, архив."""
    logs_dir = logs_dir or logs_dir_for(commands_file)
    checker = checker or Checker(commands_file)
    try:
        names = sorted(n for n in os.listdir(logs_dir) if n.endswith(".log"))
    except OSError as e:
        swallowed("review.scan_dir", e)
        names = []
    files = [_p for _p in (os.path.join(logs_dir, n) for n in names)
             if _stale(_p)]
    known: set[str] = set()
    for bucket in BUCKETS:
        known.update(store.entries(bucket))
    summary = {"total": len(files), "done": 0, "phrases": 0, "added": 0,
               "archived": 0, "errors": 0}
    with _LOCK:
        _STATE.update(summary, running=True)
    for path in files:
        try:
            for raw, core in _phrases(path, checker):
                summary["phrases"] += 1
                if core in known or checker.recognized(raw):
                    continue  # уже в базе / распознано детектором — игнор
                known.add(core)
                if store.record(UNDEFINED, core):
                    summary["added"] += 1
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
