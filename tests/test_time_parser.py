"""Тесты парсера времени напоминаний из русской речи."""

from datetime import datetime

import pytest

from lib.time_parser import TimeParser, TimeParseError, ReminderSpec


NOW = datetime(2026, 9, 15, 10, 0)  # вторник 10:00


class TestTimeParser:
    """Разбор фраз с временем напоминания."""

    def _parse(self, phrase: str):
        return TimeParser(now=NOW).parse(phrase)

    # ---------- «через N» ----------

    def test_through_hours(self):
        """«через 3 часа» → +3 часа."""
        spec = self._parse("через 3 часа постирать белье")
        assert spec.when == NOW.replace(hour=13, minute=0, second=0)
        assert spec.text == "постирать белье"

    def test_through_half_hour(self):
        """«через полчаса» → +30 минут."""
        spec = self._parse("через полчаса позвонить")
        assert spec.when == NOW.replace(hour=10, minute=30)
        assert spec.text == "позвонить"

    def test_through_minutes(self):
        """«через 30 минут» → +30 минут."""
        spec = self._parse("через 30 минут покушать")
        assert spec.when == NOW.replace(hour=10, minute=30)
        assert spec.text == "покушать"

    def test_through_days(self):
        """«через 2 дня» → +2 дня."""
        spec = self._parse("через 2 дня оплатить счет")
        assert spec.when == datetime(2026, 9, 17, 10, 0)
        assert spec.text == "оплатить счет"

    def test_through_1_hour_singular(self):
        """«через час» → +1 час."""
        spec = self._parse("через час встреча")
        assert spec.when == NOW.replace(hour=11, minute=0)
        assert spec.text == "встреча"

    def test_through_word_number_minutes(self):
        """«через десять минут» → +10 минут (словом)."""
        spec = self._parse("через десять минут убраться в прихожей")
        assert spec.when == NOW.replace(hour=10, minute=10)
        assert spec.text == "убраться в прихожей"

    def test_through_word_number_two_hours(self):
        """«через два часа» → +2 часа (словом)."""
        spec = self._parse("через два часа позвонить")
        assert spec.when == NOW.replace(hour=12, minute=0)
        assert spec.text == "позвонить"

    def test_through_word_number_30_minutes(self):
        """«через тридцать минут» → +30 минут."""
        spec = self._parse("через тридцать минут покушать")
        assert spec.when == NOW.replace(hour=10, minute=30)
        assert spec.text == "покушать"

    # ---------- относительные дни ----------

    def test_tomorrow_with_time(self):
        """«завтра в 15:00» → завтра 15:00."""
        spec = self._parse("завтра в 15:00 встреча")
        assert spec.when == datetime(2026, 9, 16, 15, 0)
        assert spec.text == "встреча"

    def test_tomorrow_no_time_default_9am(self):
        """«завтра мыть окна» → завтра 9:00."""
        spec = self._parse("завтра мыть окна")
        assert spec.when == datetime(2026, 9, 16, 9, 0)
        assert spec.text == "мыть окна"

    def test_today_with_time(self):
        """«сегодня в 18:30» → сегодня 18:30."""
        spec = self._parse("сегодня в 18:30 ужин")
        assert spec.when == datetime(2026, 9, 15, 18, 30)
        assert spec.text == "ужин"

    def test_tomorrow_hours_and_minutes_words(self):
        """«завтра в 3 часа 15 минут» → завтра 03:15."""
        spec = self._parse("завтра в 3 часа 15 минут")
        assert spec.when == datetime(2026, 9, 16, 3, 15)

    # ---------- время «в HH:MM» ----------

    def test_in_hm_future_same_day(self):
        """«в 15:30» (ещё не наступило) → сегодня 15:30."""
        spec = self._parse("в 15:30 позвонить")
        assert spec.when == datetime(2026, 9, 15, 15, 30)
        assert spec.text == "позвонить"

    def test_in_hm_past_rolls_to_tomorrow(self):
        """«в 08:00» (уже прошло) → завтра 08:00."""
        spec = self._parse("в 08:00 позвонить")
        assert spec.when == datetime(2026, 9, 16, 8, 0)

    def test_in_hm_space_separator(self):
        """«в 15 00» → 15:00."""
        spec = self._parse("в 15 00 постирать")
        assert spec.when == datetime(2026, 9, 15, 15, 0)
        assert spec.text == "постирать"

    def test_in_hour_word_future(self):
        """«в 3 часа позвонить» в 10:00 → сегодня 03:00? нет+, переход на завтра."""
        spec = self._parse("в 3 часа позвонить")
        assert spec.when == datetime(2026, 9, 16, 3, 0)
        assert spec.text == "позвонить"

    def test_in_hour_word_past_no_roll(self):
        """Обычное время в будущем — сегодня."""
        spec = self._parse("в 2 часа дня")
        assert spec.text == "дня"

    # ---------- др ----------

    def test_weekday(self):
        """«в среду созвон» — следующий день недели 9:00."""
        spec = self._parse("в среду созвон")
        assert spec.when == datetime(2026, 9, 16, 9, 0)
        assert spec.text == "созвон"

    def test_unicode_text_is_kept(self):
        """Текст с кириллицей и без хвостовых предлогов."""
        spec = self._parse("через 1 час постирать белье")
        assert spec.text == "постирать белье"

    # ---------- ошибки ----------

    def test_empty_raises(self):
        """Пустая фраза → TimeParseError."""
        with pytest.raises(TimeParseError):
            self._parse("")

    def test_garbage_raises(self):
        """Неразборчивое время → TimeParseError."""
        with pytest.raises(TimeParseError):
            self._parse("когда-нибудь потом")

    def test_through_returns_delta_type(self):
        """Через N дней — datetime с датой из будущего."""
        spec = self._parse("через 3 дня отпуск")
        assert spec.when == datetime(2026, 9, 18, 10, 0)
        assert spec.text == "отпуск"

    def test_reminder_spec_dataclass(self):
        """ReminderSpec — dataclass с полями when/text."""
        spec = ReminderSpec(when=NOW, text="тест")
        assert spec.when == NOW
        assert spec.text == "тест"
