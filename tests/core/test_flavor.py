"""Тесты чистых хелперов «оживления» (lib.core.flavor)."""

import os

from lib.core import flavor
from lib.core.flavor import build_prompt, clean_phrase, load_prompt


class TestBuildPrompt:
    """Подстановка {command}/{response} в шаблон."""

    def test_substitutes_both(self):
        template = "cmd={command}; resp={response}"
        out = build_prompt(template, "завтрак", "Приятного аппетита")
        assert out == "cmd=завтрак; resp=Приятного аппетита"

    def test_empty_falls_back_to_dash(self):
        template = "{command}|{response}"
        out = build_prompt(template, "  ", "")
        assert out == "—|—"

    def test_strips_whitespace(self):
        out = build_prompt("{command}", "  ali  ", "x")
        assert out == "ali"


class TestCleanPhrase:
    """Приведение ответа модели к одной короткой фразе."""

    def test_empty_returns_empty(self):
        assert clean_phrase("") == ""
        assert clean_phrase(None) == ""

    def test_takes_first_sentence(self):
        out = clean_phrase("Успехов! И помни про кофе.")
        assert out == "Успехов!"

    def test_strips_quotes(self):
        assert clean_phrase("«Мир держится на таких как ты»") == (
            "Мир держится на таких как ты")

    def test_strips_prefix_word(self):
        assert clean_phrase("Фраза: хорошего аппетита!") == "хорошего аппетита!"

    def test_newline_cuts(self):
        assert clean_phrase("Доброго дня\nвот ещё строка") == "Доброго дня"

    def test_collapses_whitespace(self):
        assert clean_phrase("  ровно   в   меру  ") == "ровно в меру"

    def test_clips_at_word_boundary(self):
        out = clean_phrase("слово " * 40, max_len=25)
        assert len(out) <= 25
        assert out == "слово слово слово слово"
        assert not out.endswith(" ")

    def test_no_clip_when_short(self):
        assert clean_phrase("короткая", max_len=120) == "короткая"


class TestLoadPrompt:
    """Чтение шаблона с кэшем по mtime."""

    def test_reads_utf8(self, tmp_path):
        p = tmp_path / "tpl.txt"
        p.write_text("привет {command}", encoding="utf-8")
        assert load_prompt(str(p)) == "привет {command}"

    def test_missing_returns_none(self, tmp_path):
        assert load_prompt(str(tmp_path / "nope.txt")) is None

    def test_uses_cache_by_mtime(self, tmp_path):
        p = tmp_path / "tpl.txt"
        p.write_text("версия1", encoding="utf-8")
        assert load_prompt(str(p)) == "версия1"
        # тот же mtime -> отдаём кэш, даже если файл подменили на лету
        flavor._PROMPT_CACHE[str(p)] = (p.stat().st_mtime, "кэш")
        assert load_prompt(str(p)) == "кэш"

    def test_reload_on_mtime_change(self, tmp_path):
        p = tmp_path / "tpl.txt"
        p.write_text("версия1", encoding="utf-8")
        load_prompt(str(p))
        new = p.stat().st_mtime + 2
        os.utime(p, (new, new))
        p.write_text("версия2", encoding="utf-8")
        os.utime(p, (new, new))
        assert load_prompt(str(p)) == "версия2"
