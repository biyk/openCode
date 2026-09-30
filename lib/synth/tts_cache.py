"""Локальный кэш mp3 gTTS: частые фразы не синтезируются заново.

Файлы лежат в ``temp/mp3`` под именем ``sha1(lang|text).mp3``. При попадании
в кэш дата файла обновляется (он «использован» и не будет удалён), а старые
файлы (древнее ``TTL_DAYS``) чистятся периодически. Проигрывание всегда идёт
из временной копии, поэтому канонический файл кэша остаётся нетронутым.
"""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).resolve().parents[2]
CACHE_DIR = _BASE_DIR / "temp" / "mp3"

TTL_DAYS = 7.0
# Чистку гоняем не при каждой записи, а хотя бы раз в час — каталог маленький,
# но скан каждые несколько секунд не нужен.
PURGE_INTERVAL_S = 3600.0

_last_purge = 0.0


def path_for(lang: str, text: str) -> Path:
    """Канонический путь файла кэша для пары (язык, текст)."""
    key = hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{key}.mp3"


def cached_copy(lang: str, text: str) -> Optional[str]:
    """Если фраза в кэше — отмечает использование и возвращает временную копию.

    Копия нужна, чтобы ``_play_file`` удалил именно её, а не файл кэша.
    Пустой/битый файл кэша считаем промахом. Проммах — ``None``.
    """
    src = path_for(lang, text)
    try:
        if src.stat().st_size == 0:
            return None
        os.utime(src, None)  # «использован» — переживёт purge
        dst = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
        shutil.copyfile(src, dst)
    except OSError:
        return None
    return dst


def store(lang: str, text: str, tmp_path: str) -> None:
    """Кладёт синтезированный mp3 в кэш (best-effort, атомарно)."""
    try:
        if os.path.getsize(tmp_path) == 0:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(CACHE_DIR), suffix=".tmp")
        os.close(fd)
        try:
            shutil.copyfile(tmp_path, tmp)
            os.replace(tmp, path_for(lang, text))
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
    except OSError:
        return
    _maybe_purge()


def purge(max_age_days: float = TTL_DAYS) -> int:
    """Удаляет файлы кэша старше ``max_age_days``; возвращает число удалённых."""
    cutoff = time.time() - max_age_days * 86400.0
    removed = 0
    try:
        entries = list(CACHE_DIR.glob("*.mp3")) + list(CACHE_DIR.glob("*.tmp"))
    except OSError:
        return 0
    for f in entries:
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _maybe_purge() -> None:
    """Запускает purge не чаще, чем раз в ``PURGE_INTERVAL_S`` секунд."""
    global _last_purge
    now = time.time()
    if now - _last_purge < PURGE_INTERVAL_S:
        return
    _last_purge = now
    purge()
