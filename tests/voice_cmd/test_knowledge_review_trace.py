"""Тесты локальных оценок и текстового следа распознавания (knowledge_review_trace).

Числа в логе доски — не то, что «сказала» модель, а то, что посчитал
рантайм: тот же `_similarity` и MATCH_THRESHOLD для match-шаблонов, тот же
скоринг EventMatch и TITLE_THRESHOLD для задач таблицы. Проверки — на
пределах, а не на точных float (иначе любой tweak SequenceMatcher ломает
тест, а не код).
"""

from lib.voice_cmd import knowledge_review_trace as kt


def _flat(line: str) -> str:
    """Колонки следа выровнены полем фиксированной ширины — в тестах
    сравниваем строку со схлопнутыми пробелами."""
    return " ".join(line.split())


class TestBestTemplate:
    def test_exact_prefix_is_one(self):
        cid, tpl, score = kt.best_template(
            {"stop": ["стоп музыка"]}, "стоп музыка ещё что-то")
        assert (cid, tpl) == ("stop", "стоп музыка") and score == 1.0

    def test_near_miss_visible_below_threshold(self):
        # Рантайм тут отдал бы (None, 0.0); след обязан показать промах.
        cid, _, score = kt.best_template({"tv": ["включи телевизор"]},
                                         "включи телик")
        assert cid == "tv" and 0.5 < score < kt.MATCH_THRESHOLD

    def test_longer_templates_and_empty_input_skipped(self):
        assert kt.best_template({"a": ["длинный шаблон целиком"]},
                                "нет") == ("", "", 0.0)
        assert kt.best_template({"a": ["стоп"]}, "") == ("", "", 0.0)
        assert kt.best_template({}, "стоп") == ("", "", 0.0)

    def test_yo_normalised_and_extra_spaces(self):
        _, _, score = kt.best_template({"o": ["включи ещё"]},
                                       "включи   еще")
        assert score == 1.0


class TestKeyOf:
    def test_returns_template_present_in_phrase(self):
        match = {"taskdone": ["закончил задачу", "закончил"]}
        assert kt.key_of(match, "taskdone",
                         "закончил пальцами гимнастику") == "закончил"

    def test_longest_present_template_wins(self):
        # как рантайм: при равных оценках ключ — более длинный шаблон
        match = {"taskdone": ["закончил", "закончил пальцами"]}
        assert kt.key_of(match, "taskdone",
                         "закончил пальцами гимнастику") == "закончил пальцами"

    def test_no_key_when_absent(self):
        assert kt.key_of({"stop": ["стоп музыка"]}, "stop", "тише") == ""


class TestScoreTitles:
    def test_exact_title_scores_one(self):
        title, score = kt.score_titles("Пальцевая гимнастика",
                                       ["Зарядка", "Пальцевая гимнастика"])
        assert (title, score) == ("Пальцевая гимнастика", 1.0)

    def test_partial_title_visible_but_low(self):
        title, score = kt.score_titles("пальцевая", ["Пальцевая гимнастика"])
        assert title == "Пальцевая гимнастика"
        assert 0.0 < score < kt.TITLE_THRESHOLD

    def test_composite_title_matches_any_segment(self):
        title, score = kt.score_titles("принять витамины",
                                       ["Завтрак. Принять витамины"])
        assert title == "Завтрак. Принять витамины" and score == 1.0

    def test_no_candidates(self):
        assert kt.score_titles("что-то", []) == ("", 0.0)
        assert kt.score_titles("", ["Зарядка"]) == ("", 0.0)


class TestTraceFormat:
    def test_level_shows_score_against_threshold(self):
        tr = kt.Trace("тише вода")
        tr.level("commands.json", "volumedown", 0.87, 0.9, False,
                 'ключ "громче"')
        line = _flat(tr.lines[-1])
        assert line.startswith("commands.json: volumedown (0.87 < 0.90)")
        assert 'ключ "громче"' in line and line.endswith("— не принято")

    def test_accepted_marked_phase_done(self):
        tr = kt.Trace("тише")
        tr.level("Laya", "volumedown", 0.9, 0.9, True, "уверенность модели")
        assert "(0.90 >= 0.90)" in _flat(tr.lines[-1])
        assert tr.lines[-1].endswith("— фаза завершена")

    def test_level_columns_are_aligned(self):
        # метки разной длины не должны разъезжаться по таб-стопам
        tr = kt.Trace("тише")
        tr.level("Laya", "x", None, None, True)
        tr.level("LLM Race(omni+lmstudio)", "y", None, None, True)
        a, b = tr.lines[1], tr.lines[2]
        assert a.index("x") > len("Laya:") and b.index("y") == a.index("x")

    def test_level_without_score(self):
        tr = kt.Trace("тише")
        tr.level("LLM race", "volumedown", None, None, True)
        assert _flat(tr.lines[-1]) == "LLM race: volumedown — фаза завершена"

    def test_empty_value_and_skipped_reason(self):
        tr = kt.Trace("ы ы ы")
        tr.level("Laya", "", 0.1, 0.9, False)
        assert _flat(tr.lines[-1]) == "Laya: — (0.10 < 0.90) — не принято"
        tr.skipped("LLM", "фаза 1 завершена: Laya")
        assert _flat(tr.lines[-1]) == (
            "LLM: пропущено, причина (фаза 1 завершена: Laya)")

    def test_result_line(self):
        tr = kt.Trace("закончил пальцами гимнастику")
        tr.result("taskdone", "закончил", "Пальцевая гимнастика")
        assert tr.lines[-1] == ('итог:\tкоманда taskdone ключ "закончил" '
                                'параметры "Пальцевая гимнастика"')
        tr.result("", "", "")
        assert tr.lines[-1] == "итог:\tкоманда — ключ — параметры —"

    def test_phrase_and_header(self):
        tr = kt.Trace("стоп музыка")
        assert tr.lines[0] == "фраза:\tстоп музыка"
        tr.phase("1\tопределение команды")
        assert tr.lines[1] == "фаза 1\tопределение команды"
        tr.note("это задача")
        assert tr.lines[2] == "  это задача"
        assert tr.text().startswith("фраза:")
        assert "=== прогон 12:00: фраз 3, распознано 2 ===" == \
            kt.run_header("12:00", 3, 2)
