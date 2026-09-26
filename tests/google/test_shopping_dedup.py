"""Тесты совпадения названий списка покупок (lib/google/shopping_dedup.py).

Два поведения: поиск дубликата перед добавлением (выключен по умолчанию —
флаг `shopping.dedup.enabled`) и поиск позиции на удаление («купил X»),
который работает всегда. Проверяем нормализацию, подстроку, порог
нечёткого сравнения и что выключенный dedup никогда не блокирует
добавление.
"""

from lib.google.shopping_dedup import (
    DEFAULT_THRESHOLD, fuzzy_enabled, find_duplicate, find_item, normalize,
    threshold)

OFF = {"enabled": False, "fuzzy": False, "threshold": 0.9}
EXACT = {"enabled": True, "fuzzy": False, "threshold": 0.9}
FUZZY = {"enabled": True, "fuzzy": True, "threshold": 0.9}

EXISTING = [{"row": 2, "name": "Молоко 2л"},
            {"row": 3, "name": "Гречка"},
            {"row": 4, "name": "Хлеб цельнозерновой"}]


def test_normalize_cases_punctuation_and_yo():
    """Регистр, ё/е, пунктуация и лишние пробелы не влияют на сравнение."""
    assert normalize("  МОЛОКО, 2л ") == "молоко 2л"
    assert normalize("ёлка") == "елка"
    assert normalize("") == ""


def test_duplicate_search_is_off_by_default():
    """Выключенный dedup — всегда None: дубликат не блокирует добавление."""
    assert find_duplicate("молоко", EXISTING) is None
    assert find_duplicate("молоко", EXISTING, OFF) is None
    assert find_duplicate("Гречка", EXISTING, None) is None


def test_exact_duplicate_ignores_case_and_punctuation():
    """Точное совпадение по нормализованному названию — метод exact."""
    hit = find_duplicate("МОЛОКО 2Л", EXISTING, EXACT)
    assert hit == {"row": 2, "name": "Молоко 2л", "method": "exact"}
    assert find_duplicate("масло", EXISTING, EXACT) is None


def test_exact_mode_does_not_treat_substring_as_duplicate():
    """Без fuzzy «гречка» и «гречка на молоке» — разные товары."""
    other = [{"row": 5, "name": "Гречка на молоке"}]
    assert find_duplicate("гречка", other, EXACT) is None


def test_fuzzy_duplicate_only_when_enabled_and_over_threshold():
    """Нечёткое сравнение включается флагом и считает порог (c в ответе)."""
    near = [{"row": 2, "name": "гречка ядрица"}]
    assert find_duplicate("гречка ядррица", near, EXACT) is None
    hit = find_duplicate("гречка ядррица", near, FUZZY)
    assert hit is not None and hit["method"] == "fuzzy"
    assert hit["score"] >= 0.9

    far = [{"row": 2, "name": "молоко"}]
    assert find_duplicate("хлеб", far, FUZZY) is None


def test_fuzzy_needs_dedup_enabled_too():
    """fuzzy без enabled не действует: дедуп включается одним флагом."""
    cfg = {"enabled": False, "fuzzy": True}
    assert fuzzy_enabled(cfg) is False
    assert find_duplicate("гречка ядррица",
                          [{"row": 2, "name": "гречка ядрица"}],
                          cfg) is None


def test_find_item_matches_for_removal_without_dedup_config():
    """Удаление ищет всегда: точное → подстрока (без конфига)."""
    assert find_item("молоко", EXISTING)["row"] == 2
    assert find_item("молоко", EXISTING)["method"] == "contains"
    assert find_item("Гречка", EXISTING)["method"] == "exact"
    assert find_item("цельнозерновой", EXISTING)["row"] == 4
    assert find_item("кефир", EXISTING) is None
    assert find_item("", EXISTING) is None
    assert find_item("молоко", []) is None


def test_find_item_prefers_the_longest_containing_name():
    """Из нескольких подходящих берётся самое длинное название."""
    rows = [{"row": 2, "name": "хлеб"}, {"row": 3, "name": "хлеб цельнозернов"}]
    assert find_item("хлеб цельнозерновый", rows)["row"] == 3


def test_find_item_uses_fuzzy_only_when_config_allows_it():
    """Опечатка в названии ловится fuzzy, если он разрешён конфигом."""
    assert find_item("гречку", EXISTING, EXACT) is None
    hit = find_item("гречку", EXISTING, {"enabled": True, "fuzzy": True,
                                         "threshold": 0.7})
    assert hit is not None and hit["method"] == "fuzzy"


def test_threshold_falls_back_on_junk_config():
    """Порог: валидное число из конфига, иначе DEFAULT_THRESHOLD."""
    assert threshold({"threshold": 0.7}) == 0.7
    assert threshold({"threshold": "abc"}) == DEFAULT_THRESHOLD
    assert threshold({"threshold": 0}) == DEFAULT_THRESHOLD
    assert threshold({"threshold": 5}) == DEFAULT_THRESHOLD
    assert threshold(None) == DEFAULT_THRESHOLD
