# lib/voice_cmd/knowledge_review_unconfirm.py
"""Снятие статуса «подтверждено» — перенос фразы в «Не распознано».

Правило доски: настоящее удаление живёт только на странице «Не распознано».
На «Подтверждено» и «Лайе» крестик ✕ меняет статус: фраза уезжает в undefined,
а не стирается. Вынесено из knowledge_review_board под лимит 200 строк.
"""

from __future__ import annotations

import json
from typing import Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge import BUCKETS, UNDEFINED, KnowledgeStore
from lib.voice_cmd.knowledge_common import normalize_core
from lib.voice_cmd.knowledge_learn import atomic_dump_json


def bucket_of(store: KnowledgeStore, text: str) -> Optional[str]:
    """Корзина, где сейчас лежит фраза (ключи — norm-ядра, вход нормализуем)."""
    core = normalize_core(text)
    for b in BUCKETS:
        if core in store.entries(b):
            return b
    return None


def drop_match(commands_file: str, core: str) -> int:
    """Убирает из match шаблоны с таким norm-ядром; возвращает сколько снято.

    Пустой список чистится вместе с cid: команда без match-фраз больше никем
    не матчится, но сама запись команды и прочие секции не тронуты.
    """
    try:
        with open(commands_file, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        swallowed("review.unconfirm.read", e)
        return 0
    match = data.get("match") or {}
    removed = 0
    for cid in list(match):
        kept = [t for t in match[cid] if normalize_core(t) != core]
        if len(kept) != len(match[cid]):
            removed += len(match[cid]) - len(kept)
            if kept:
                match[cid] = kept
            else:
                del match[cid]
    if removed:
        data["match"] = match
        atomic_dump_json(commands_file, data, "review.unconfirm.write")
    return removed


def to_undefined(store: KnowledgeStore, text: str) -> bool:
    """Переносит фразу в «Не распознано», ничего не стирая.

    Запись из confirmed/laya переезжает целиком (это смена статуса), а locked-
    строка commands.json записи в базе не имеет — для неё заводится новая
    undefined-запись, иначе фраза просто исчезла бы с доски.
    """
    bucket = bucket_of(store, text)
    if bucket == UNDEFINED:
        return True
    if bucket is None:
        return store.record(UNDEFINED, normalize_core(text))
    return store.demote(text)


def unconfirm_phrase(store: KnowledgeStore, commands_file: str,
                     text: str) -> dict:
    """✕ на «Подтверждено» — НЕ удаление: фраза переносится в «Не распознано».

    match-шаблон в commands.json и есть статус «подтверждено» для locked-
    строки, поэтому он снимается; знание понижается до undefined.
    """
    removed = drop_match(commands_file, normalize_core(text))
    return {"match": removed, "moved": to_undefined(store, text)}
