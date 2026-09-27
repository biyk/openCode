"""Тесты текста названий мероприятий (lib.core.event_text)."""

from lib.core.event_text import clean_title, strip_noise, title_segments


class TestCleanTitle:
    def test_cuts_parens_brackets_braces(self):
        assert clean_title("Утренник (сад) [день] {заметка}").strip() == \
            "Утренник"

    def test_cuts_emoji_and_symbols(self):
        assert "Утренник" in clean_title("\u25b8 Утренник \U0001f30c 🎉")

    def test_keeps_letters_digits_spaces(self):
        assert clean_title("Тест 2 дюз") == "Тест 2 дюз"

    def test_none_safe(self):
        assert clean_title(None) == ""


class TestTitleSegments:
    def test_splits_compound_on_dot(self):
        assert title_segments("Завтрак. Принять витамины") == \
            ["Завтрак", "Принять витамины"]

    def test_two_segments_practice_event(self):
        assert title_segments("Распечатать тест дюз. прочистка принтера") == \
            ["Распечатать тест дюз", "прочистка принтера"]

    def test_abbrev_dot_does_not_split(self):
        assert title_segments("Молоко 2 шт.") == ["Молоко 2 шт."]

    def test_single_title_is_one_segment(self):
        assert title_segments("Прогулка") == ["Прогулка"]

    def test_comma_and_semicolon_split(self):
        assert title_segments("Молоко, Хлеб; Витаминки") == \
            ["Молоко", "Хлеб", "Витаминки"]

    def test_drops_empty_and_tiny_pieces(self):
        assert "" not in title_segments("Завтрак.  . Витамины")


class TestStripNoise:
    def test_strips_leading_noise_words(self):
        assert strip_noise("задачу помыть пол") == "помыть пол"

    def test_yo_normalized_in_noise_word(self):
        assert strip_noise("мероприятие отчёт") == "отчёт"

    def test_keeps_real_name(self):
        assert strip_noise("почистить зубы") == "почистить зубы"
