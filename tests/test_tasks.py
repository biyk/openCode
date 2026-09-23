"""Тесты задач: разбор фраз, создание."""


from lib.tasks import TaskHandler, _clean_candidate


class TestCleanCandidate:
    """Удаление триггеров и заполнителей из фразы."""

    def test_basic(self):
        """«добавь задачу купить хлеб» → «купить хлеб»."""
        assert _clean_candidate("добавь задачу купить хлеб") == "купить хлеб"

    def test_with_me(self):
        """«добавь мне задачу написать отчёт» → «написать отчёт»."""
        assert _clean_candidate(
            "добавь мне задачу написать отчёт") == "написать отчёт"

    def test_me_plus_pozhaluista(self):
        """«добавь мне пожалуйста задачу убраться» → «убраться»."""
        assert _clean_candidate(
            "добавь мне пожалуйста задачу убраться") == "убраться"

    def test_sozdai(self):
        """«создай задачу позвонить маме» → «позвонить маме»."""
        assert _clean_candidate("создай задачу позвонить маме") == "позвонить маме"

    def test_sozdai_vosk_nominative(self):
        """Vosk «создай задача починить лампочку» → «починить лампочку»."""
        assert _clean_candidate(
            "создай задача починить лампочку ванной") == "починить лампочку ванной"

    def test_zapishi(self):
        """«запиши в задачи купить молоко» → «купить молоко»."""
        assert _clean_candidate("запиши в задачи купить молоко") == "купить молоко"

    def test_novaya(self):
        """«новая задача выгулять собаку» → «выгулять собаку»."""
        assert _clean_candidate("новая задача выгулять собаку") == "выгулять собаку"

    def test_truncated_trigger_not_consumed(self):
        """«добавь задачу-минимум» → триггер по границе слова не срезался
        хвостом, но фраза считается по полному совпадению начала."""
        assert _clean_candidate("добавь задачу убираться") == "убираться"

    def test_empty_after_clean(self):
        """Только слово «добавь задачу» — пустой кандидат."""
        assert _clean_candidate("добавь задачу") == ""

    def test_trailing_pozhaluista(self):
        """«пожалуйста» в конце после триггера удаляется."""
        assert _clean_candidate(
            "добавь задачу купить хлеб пожалуйста") == "купить хлеб"


class TestIsTask:
    """Распознавание команды задачи."""

    def _handler(self, mock_google=None):
        return TaskHandler(google=mock_google or type(
            "G", (), {"create_task": lambda self, **kw: "t"})())

    def test_positive(self):
        """Фраза начинается с «добавь задачу» → True."""
        assert self._handler().is_task("добавь задачу купить хлеб")

    def test_negative(self):
        """Обычный текст — не задача."""
        assert not self._handler().is_task("включи ютуб")

    def test_variants(self):
        """Разные варианты триггеров распознаются."""
        h = self._handler()
        for p in ["добавь задачу", "создай задачу", "создай задача",
                  "запиши в задачи", "новая задача"]:
            assert h.is_task(f"{p} позвонить")


class TestCreate:
    """Извлечение названия задачи."""

    def _handler(self):
        return TaskHandler()

    def test_basic(self):
        """«добавь задачу купить хлеб» → «купить хлеб»."""
        assert self._handler().create("добавь задачу купить хлеб") == \
            "купить хлеб"

    def test_with_me(self):
        """«добавь мне задачу позвонить маме» → «позвонить маме»."""
        assert self._handler().create("добавь мне задачу позвонить маме") == \
            "позвонить маме"

    def test_empty_phrase_returns_none(self):
        """Пустая фраза после очистки → None."""
        h = self._handler()
        assert h.create("добавь задачу") is None


class TestAddTask:
    """Создание задачи через API."""

    def _mock(self, **methods):
        return type("G", (), methods)()

    def test_success(self):
        """Успешное создание задачи → task_id."""
        mock_google = self._mock(create_task=lambda self, **kw: "task123")
        handler = TaskHandler(google=mock_google)
        assert handler.add_task("купить хлеб") == "task123"

    def test_failure_returns_none(self):
        """Ошибка Google API → None."""
        mock_google = self._mock(create_task=lambda self, **kw: (_ for _ in ()).throw(
            Exception("no creds")))
        handler = TaskHandler(google=mock_google)
        assert handler.add_task("купить хлеб") is None

    def test_clean_candidate_uses_keyword(self):
        """add_task передаёт название вторым аргументом."""
        seen = {}

        def fake_create(self, title=None, notes=None):
            seen["title"] = title
            seen["notes"] = notes
            return "task_ok"

        mock_google = self._mock(create_task=fake_create)
        handler = TaskHandler(google=mock_google)
        title = handler.create("добавь задачу купить хлеб")
        eid = handler.add_task(title)
        assert eid == "task_ok"
        assert seen["title"] == "купить хлеб"
        assert seen["notes"] is None


class TestIntegration:
    """Сквозной сценарий создания."""

    def test_full_flow(self):
        """Полный сценарий: текст → задача создана."""
        created = {}

        def fake_create(self, title=None, notes=None):
            created["title"] = title
            created["notes"] = notes
            return "task_ok"

        handler = TaskHandler(google=type(
            "G", (), {"create_task": fake_create})())
        title = handler.create("добавь задачу купить хлеб")
        assert title == "купить хлеб"
        eid = handler.add_task(title)
        assert eid == "task_ok"
        assert created["title"] == "купить хлеб"
