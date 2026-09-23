"""Тесты задач: подбор незавершённых по названию."""


from lib.tasks import TaskHandler


class TestCompleteMatching:
    """Exact/substring/fuzzy совпадения."""

    def test_exact_match(self):
        """Точное совпадение по названию → выполнена."""
        tasks = [{"id": "t1", "title": "Купить хлеб", "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"id": task_id,
                                                    "status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching("купить хлеб")
        assert len(report["matched"]) == 1
        assert report["matched"][0]["title"] == "Купить хлеб"
        assert report["matched"][0]["exact"] is True

    def test_case_insensitive_and_whitespace(self):
        """Регистр и хвостовые пробелы не важны."""
        tasks = [{"id": "t1", "title": "  Купить ХЛЕБ  ", "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching("купить хлеб")
        assert len(report["matched"]) == 1

    def test_substring_match(self):
        """Нет точного, но есть по вхождению → помечается как exact False."""
        tasks = [
            {"id": "t1", "title": "Купить хлеб в магазине",
             "status": "needsAction"},
            {"id": "t2", "title": "Позвонить маме", "status": "needsAction"},
        ]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching("хлеб")
        assert len(report["matched"]) == 1
        assert report["matched"][0]["id"] == "t1"
        assert report["matched"][0]["exact"] is False

    def test_no_match(self):
        """Нет совпадений → пустой отчёт."""
        tasks = [{"id": "t1", "title": "Позвонить маме",
                  "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching("постирать")
        assert report["matched"] == []

    def test_empty_title_returns_empty(self):
        """Пустое название → пустой отчёт, API не трогается."""
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: (_ for _ in ()).throw(
                Exception("not called")),
            "complete_task": lambda self, task_id: None,
        })()
        report = TaskHandler(google=google).complete_matching("   ")
        assert report["matched"] == []

    def test_api_error_returns_empty(self):
        """Ошибка загрузки списка → пустой отчёт без падения."""
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: (_ for _ in ()).throw(
                Exception("no creds")),
        })()
        report = TaskHandler(google=google).complete_matching("хлеб")
        assert report["matched"] == []

    def test_fuzzy_match(self):
        """Фонетическая ошибка Vosk «починить» vs «подчинить в» → fuzzy.

        Реальная задача из лога: «починить лампочку ванной» должна
        находить «подчинить лампочку в ванной» нечётким совпадением.
        """
        tasks = [{"id": "t1", "title": "Позвонить маме",
                  "status": "needsAction"},
                 {"id": "t2", "title": "подчинить лампочку в ванной",
                  "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching(
            "починить лампочку ванной")
        assert len(report["matched"]) == 1
        assert report["matched"][0]["id"] == "t2"
        assert report["matched"][0]["method"] == "fuzzy"
        assert report["matched"][0]["exact"] is False

    def test_fuzzy_below_threshold_no_match(self):
        """Совсем другая задача ниже порога не завершается."""
        tasks = [{"id": "t1", "title": "Танго", "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching(
            "починить лампочку ванной")
        assert report["matched"] == []

    def test_substring_method_flag(self):
        """Подстрочное совпадение помечается method=substring."""
        tasks = [{"id": "t1", "title": "Купить хлеб в магазине",
                  "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching("хлеб")
        assert report["matched"][0]["method"] == "substring"

    def test_exact_method_flag(self):
        """Точное совпадение помечается method=exact."""
        tasks = [{"id": "t1", "title": "Танго", "status": "needsAction"}]
        google = type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()
        report = TaskHandler(google=google).complete_matching("танго")
        report = TaskHandler(google=google).complete_matching("Танго")
        assert report["matched"][0]["method"] == "exact"
        assert report["matched"][0]["exact"] is True
