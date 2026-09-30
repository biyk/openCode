"""тесты lib/rest_check.py — question/parse/classify structured-ответа модели."""

import pytest

from lib import rest_check
from lib.rest_check import RestAnswer, parse_rest_answer

GOOD = "Ответ: да\nВероятность: 80%\nОбъяснение: это видео, значит отдых."
NO = "Ответ: нет\nВероятность: 95%\nОбъяснение: редактор кода — работа."
DONT_KNOW = "Ответ: не знаю\nВероятность: 50%\nОбъяснение: заголовок мусорный."


class FakeClient:
    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def ask(self, text):
        self.asked.append(text)
        return self.answer


class SequenceClient:
    """Отдаёт ответы по списку; после исчерпания повторяет последний."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []

    def ask(self, text):
        self.asked.append(text)
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class TestRestPrompt:
    def test_includes_title_and_field_labels(self):
        p = rest_check.rest_prompt("YouTube — ролик")
        assert "YouTube — ролик" in p
        for token in ("Ответ:", "Вероятность:", "Объяснение:"):
            assert token in p


class TestParseRestAnswer:
    def test_yes(self):
        assert parse_rest_answer(GOOD) == RestAnswer(
            "да", 80, "это видео, значит отдых.", True)

    def test_no(self):
        res = parse_rest_answer(NO)
        assert (res.answer, res.probability, res.is_rest) == ("нет", 95, False)

    def test_dont_know_is_not_rest(self):
        res = parse_rest_answer(DONT_KNOW)
        assert res.answer == "не знаю" and res.is_rest is False

    @pytest.mark.parametrize("raw", [
        "Ответ:Да.\nВероятность: 70",
        "ответ - да\nвероятность: 70%\nобъяснение: ок",
        "Ответ: да, это отдых\nВероятность: 60%\nОбъяснение: х",
    ])
    def test_varied_format_is_rest(self, raw):
        assert parse_rest_answer(raw).is_rest is True

    def test_probability_without_percent(self):
        assert parse_rest_answer("Ответ: нет\nВероятность: 40").probability == 40

    def test_extra_text_before_fields(self):
        assert parse_rest_answer("Конечно, сейчас:\n" + GOOD).is_rest is True

    @pytest.mark.parametrize("raw", [
        None, "", "   ", "ВИДЕО", "полный мусор без полей"])
    def test_unparseable_not_rest(self, raw):
        res = parse_rest_answer(raw)
        assert res.is_rest is False and res.probability is None


class TestClassify:
    def test_empty_title_skips_request(self):
        c = FakeClient(GOOD)
        assert rest_check.classify("", c) == RestAnswer("", None, "", False)
        assert c.asked == []

    def test_asks_once_and_parses_yes(self):
        c = FakeClient(GOOD)
        assert rest_check.classify("Игра", c).is_rest is True
        assert len(c.asked) == 1

    def test_prompt_sent_to_client(self):
        c = FakeClient(NO)
        rest_check.classify("Excel", c)
        assert c.asked == [rest_check.rest_prompt("Excel")]

    def test_model_garbage_not_rest(self):
        assert rest_check.classify("фильм", FakeClient("ВИДЕО")).is_rest is False


class TestClassifyUntilAnswer:
    """Крутимся до разборчатого ответа: таймаут/мусор → retry, да/нет → стоп."""

    def test_retries_until_parseable(self, mocker):
        sleep = mocker.patch("lib.rest_check.time.sleep")
        c = SequenceClient(["Read timed out", "мусор без полей", GOOD])
        res = rest_check.classify_until_answer("Игра", c, delay_s=1)
        assert res.is_rest is True
        assert len(c.asked) == 3                 # два пролёта + успех
        assert sleep.call_count == 2             # пауза только между попытками

    def test_returns_immediately_on_answer(self, mocker):
        mocker.patch("lib.rest_check.time.sleep")
        c = SequenceClient([NO])
        assert rest_check.classify_until_answer("Excel", c).answer == "нет"
        assert len(c.asked) == 1

    def test_max_attempts_gives_up_with_last(self, mocker):
        mocker.patch("lib.rest_check.time.sleep")
        c = FakeClient("полный мусор")
        res = rest_check.classify_until_answer(
            "Игра", c, delay_s=1, max_attempts=2)
        assert res == RestAnswer("", None, "", False)
        assert len(c.asked) == 2                 # упёрлись в лимит

    def test_empty_title_skips_request(self):
        c = SequenceClient([GOOD])
        assert rest_check.classify_until_answer(
            "", c) == RestAnswer("", None, "", False)
        assert c.asked == []
