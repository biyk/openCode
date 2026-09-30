"""Чистые хелперы «оживления» ответа: шаблон промпта и нормализация фразы.

Здесь нет ни TTS, ни потоков, ни LLM — только текст на вход/выход, чтобы
логику было легко тестировать. Дефолты секции `flavor` держим тут (в
targets/<host>/commands.json те же ключи переопределяются): tuning.py уже
на пределе лимита строк, поэтому константы флейвора живёт в своём модуле.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

# ─── Дефолты секции `flavor` (оверрайд — commands.json: flavor.*) ──────────

FLAVOR_ENABLED = True
# Предельная длина итоговой фразы (символов): длиннее — режем по слову.
FLAVOR_MAX_LEN = 120
# Сколько секунд ждать ответ LLM (race.classify): сверх — пропускаем добавку.
FLAVOR_TIMEOUT_S = 15
# Потолок ожидания, пока закончится основная озвучка, прежде чем вставить
# свою фразу (сек): дольше ждать не смысл — пользователь уже отвлёкся.
FLAVOR_SPEAK_WAIT_S = 6.0
# Путь к шаблону инструкции (относительно корня репозитория).
FLAVOR_PROMPT_PATH = "prompts/flavor_template.txt"

# Кавычки/буковки, которые модель может обернуть вокруг фразы.
_QUOTES = "\"'«»„“”‚‘’…"
# Ведущее слово-префикс ответа («Фраза:», «Добавка -» и т.п.) — снимаем.
_PREFIX_RE = re.compile(
    r"^\s*(?:фраза|добавка|дополнение|реплика|ответ)\s*[:=\-–—]\s*",
    re.IGNORECASE)
# Граница первой законченной фразы (точка/восклицание/вопросительный/перенос).
_SENTENCE_RE = re.compile(r"[.!?…]\s|\n")


def load_prompt(path: str) -> Optional[str]:
    """Читает шаблон промпта (utf-8) с кэшем по mtime; None — если нет/сбой."""
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    cached = _PROMPT_CACHE.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    _PROMPT_CACHE[path] = (mtime, text)
    return text


_PROMPT_CACHE: dict = {}


def build_prompt(template: str, command: str, response: str) -> str:
    """Подставляет {command}/{response} в шаблон (через replace, не format)."""
    return (template
            .replace("{command}", (command or "").strip() or "—")
            .replace("{response}", (response or "").strip() or "—"))


def clean_phrase(raw: Optional[str], max_len: int = FLAVOR_MAX_LEN) -> str:
    """Приводит ответ модели к ОДНОЙ короткой фразе; пусто — если нечего сказать.

    Снимает кавычки и слово-префикс, берёт первое предложение (или строку),
    схлопывает пробелы и режет по границе слова, если длиннее max_len.
    """
    if not raw:
        return ""
    text = raw.strip()
    text = _PREFIX_RE.sub("", text)
    text = _first_sentence(text).strip(_QUOTES).strip()
    text = re.sub(r"\s+", " ", text).strip()
    return _clip(text, max_len)


def _first_sentence(text: str) -> str:
    """Отрезает первое законченное предложение (по .!?… или переносу строки)."""
    m = _SENTENCE_RE.search(text)
    if m:
        return text[:m.end()].strip()
    return text


def _clip(text: str, max_len: int) -> str:
    """Режет по max_len по границе слова (не рубит середину слова)."""
    if max_len <= 0 or len(text) <= max_len:
        return text
    cut = text[:max_len]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(_QUOTES + " ,;:")
