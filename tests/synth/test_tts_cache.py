"""Тестируют lib/synth/tts_cache: кэш mp3 gTTS в temp/mp3."""

import os
import time
from pathlib import Path

import pytest

from lib.synth import tts_cache
from lib.tts import TextToSpeech


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "mp3"
    monkeypatch.setattr(tts_cache, "CACHE_DIR", d)
    return d


def _mk(lang, text, data=b"ID3fake"):
    """Создаёт временный mp3-файл (мимитрует синтез) и возвращает путь."""
    fd, name = tts_cache.tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    Path(name).write_bytes(data)
    return name


class TestCacheRoundtrip:
    def test_miss_returns_none(self, cache_dir):
        assert tts_cache.cached_copy("ru", "Вы умничка!") is None

    def test_store_then_reuse(self, cache_dir):
        src = _mk("ru", "Вы умничка!")
        tts_cache.store("ru", "Вы умничка!", src)
        assert tts_cache.path_for("ru", "Вы умничка!").exists()

        copy = tts_cache.cached_copy("ru", "Вы умничка!")
        assert copy is not None
        assert Path(copy).read_bytes() == b"ID3fake"
        # Проигрывание удалит копию, а канонический файл кэша останется.
        os.unlink(copy)
        assert tts_cache.path_for("ru", "Вы умничка!").exists()

    def test_empty_cache_file_is_miss(self, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        tts_cache.path_for("ru", "Пусто").write_bytes(b"")
        assert tts_cache.cached_copy("ru", "Пусто") is None

    def test_store_skips_empty_source(self, cache_dir):
        empty = Path(tts_cache.tempfile.mkstemp(suffix=".mp3")[1])
        empty.write_bytes(b"")
        tts_cache.store("ru", "Пусто", str(empty))
        assert not tts_cache.path_for("ru", "Пусто").exists()


class TestPurge:
    def test_hit_touches_mtime_so_survives_purge(self, cache_dir):
        src = _mk("ru", "Готово")
        tts_cache.store("ru", "Готово", src)
        canon = tts_cache.path_for("ru", "Готово")
        old = time.time() - 8 * 86400
        os.utime(canon, (old, old))

        assert tts_cache.cached_copy("ru", "Готово") is not None
        assert canon.stat().st_mtime > time.time() - 60
        assert tts_cache.purge(max_age_days=7) == 0
        assert canon.exists()

    def test_purge_removes_old_keeps_fresh(self, cache_dir):
        src = _mk("ru", "Старое")
        tts_cache.store("ru", "Старое", src)
        src2 = _mk("ru", "Свежее")
        tts_cache.store("ru", "Свежее", src2)
        old = time.time() - 8 * 86400
        os.utime(tts_cache.path_for("ru", "Старое"), (old, old))

        removed = tts_cache.purge(max_age_days=7)
        assert removed == 1
        assert not tts_cache.path_for("ru", "Старое").exists()
        assert tts_cache.path_for("ru", "Свежее").exists()


class TestSpeakIntegration:
    def test_second_speak_uses_cache_no_network(self, cache_dir, monkeypatch):
        calls = []

        class FakeG:
            def __init__(self, **kwargs):
                pass

            def save(self, path):
                calls.append(path)
                Path(path).write_bytes(b"ID3fake")

        monkeypatch.setattr("lib.synth.tts_engines.gTTS", FakeG)
        tts = TextToSpeech()

        first = tts.speak("Вы умничка!")
        second = tts.speak("Вы умничка!")

        assert first and second
        assert len(calls) == 1  # сеть была ровно один раз
        # Удалем временные копии проигрывания за собой.
        for p in (first, second):
            try:
                os.unlink(p)
            except OSError:
                pass
