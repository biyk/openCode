"""Тесты задач: разбор фразы завершения."""


from lib.tasks import TaskHandler


class TestCompleteParse:
    """Триггеры завершения и извлечение названия."""

    def _handler(self):
        return TaskHandler()

    def test_is_complete_task(self):
        """Определение фразы завершения."""
        h = self._handler()
        assert h.is_complete_task("заверши задачу купить хлеб")
        assert h.is_complete_task("выполни задачу позвонить маме")
        assert h.is_complete_task("отметь задачу выполненной убраться")
        assert not h.is_complete_task("добавь задачу купить хлеб")
        assert not h.is_complete_task("включи ютуб")

    def test_basic(self):
        """«заверши задачу купить хлеб» → «купить хлеб»."""
        assert self._handler().complete_parse(
            "заверши задачу купить хлеб") == "купить хлеб"

    def test_zakroy(self):
        """«закрой задачу написать отчёт» → «написать отчёт»."""
        assert self._handler().complete_parse(
            "закрой задачу написать отчёт") == "написать отчёт"

    def test_vyipolnit_infinitive(self):
        """Инфинитив «выполнить задачу …» распознаётся как завершение."""
        h = self._handler()
        assert h.is_complete_task("выполнить задачу помыть полы")
        assert h.complete_parse("выполнить задачу помыть полы") == "помыть полы"

    def test_vyipolniv_gerund(self):
        """Деепричастие «выполнив задачу …» распознаётся как завершение."""
        h = self._handler()
        assert h.is_complete_task("выполнив задачу починить лампочку ванной")
        assert h.complete_parse(
            "выполнив задачу починить лампочку ванной") == \
            "починить лампочку ванной"

    def test_with_pozhaluista(self):
        """«заверши мне пожалуйста задачу убраться» → «убраться»."""
        assert self._handler().complete_parse(
            "заверши мне пожалуйста задачу убраться") == "убраться"

    def test_empty_phrase_returns_none(self):
        """Пустая фраза после очистки → None."""
        h = self._handler()
        assert h.complete_parse("заверши задачу") is None
