"""Тесты обработчика задач (TaskHandler)."""

import base64

from lib.tasks import TaskHandler, _clean_candidate, _decode_arg, main


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
    """Определение, является ли текст командой задачи."""

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
    """Извлечение названия задачи из текста."""

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
    """Вызов Google Tasks API (mock)."""

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
    """Интеграция полного цикла: текст → mock tasks API."""

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


class TestCompleteParse:
    """Извлечение названия задачи из фразы завершения."""

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


class TestCompleteMatching:
    """Поиск и завершение задач по названию (mock)."""

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


class TestCompleteCli:
    """CLI `python -m lib.tasks complete ...` для скилла task-complete."""

    def _google(self):
        tasks = [{"id": "t1", "title": "подчинить лампочку в ванной",
                  "status": "needsAction"}]
        return type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()

    def test_main_complete_fuzzy(self, capsys):
        """CLI находит задачу нечётким совпадением и печатает отчёт."""
        import lib.tasks as tasks_module
        tasks_module.TaskHandler = lambda google=None: TaskHandler(
            google=google or self._google())
        phrase = base64.b64encode(
            "выполнить задачу починить лампочку в ванной пожалуйста".encode()
        ).decode("ascii")
        try:
            code = main(["complete", f"--b64:{phrase}"])
        finally:
            tasks_module.TaskHandler = TaskHandler
        out = capsys.readouterr().out
        assert code == 0
        assert "title: починить лампочку в ванной" in out
        assert '"method": "fuzzy"' in out
        assert '"title": "подчинить лампочку в ванной"' in out

    def test_main_usage(self, capsys):
        """Без аргументов CLI печатает usage и возвращает 2."""
        assert main([]) == 2
        assert "usage" in capsys.readouterr().out

    def test_decode_arg(self):
        """--b64: декодируется, обычный текст остаётся как есть."""
        phrase = "купить хлеб — завтра"
        b64 = base64.b64encode(phrase.encode("utf-8")).decode("ascii")
        assert _decode_arg(f"--b64:{b64}") == phrase
        assert _decode_arg("просто текст") == "просто текст"
        assert _decode_arg("--b64:не-валид!base64") == "--b64:не-валид!base64"

    def test_decode_arg_urlsafe_and_unpadded(self):
        """--b64: терпим к url-safe алфавиту (-_) и отсутствию паддинга."""
        phrase = "выполни задачу починить лампочку в ванной"
        b64 = base64.b64encode(phrase.encode("utf-8")).decode("ascii")
        url_safe = b64.replace("+", "-").replace("/", "_")
        unpadded = url_safe.rstrip("=")
        assert _decode_arg(f"--b64:{unpadded}") == phrase

    def test_main_complete_plain_text(self, capsys):
        """CLI завершает задачу по обычному текстовому аргументу (без b64)."""
        import lib.tasks as tasks_module
        tasks_module.TaskHandler = lambda google=None: TaskHandler(
            google=google or self._google())
        try:
            code = main(
                ["complete", "выполни задачу починить лампочку в ванной"])
        finally:
            tasks_module.TaskHandler = TaskHandler
        out = capsys.readouterr().out
        assert code == 0
        assert '"method": "fuzzy"' in out
        assert '"title": "подчинить лампочку в ванной"' in out

    def _google_create(self, task_id="task-9", auth=True):
        from lib.google_tasks import GoogleOAuthError

        class G:
            def create_task(self, title, notes=None):
                return task_id

            def is_ready(self):
                return auth

            def authorize(self):
                if not auth:
                    raise GoogleOAuthError("нет consent")
        return G()

    def test_main_create_task(self, capsys):
        """CLI создаёт задачу: create <фраза> → task_id, код 0, «Готово»."""
        import lib.tasks as tasks_module
        tasks_module.TaskHandler = lambda google=None: TaskHandler(
            google=google or self._google_create())
        voiced = []
        fake_tts = type("T", (), {
            "speak_and_play": lambda self, text: voiced.append(text),
        })()
        real_tts = tasks_module.TextToSpeech
        tasks_module.TextToSpeech = lambda *a, **k: fake_tts
        try:
            code = main(["create", "создай задачу убраться у кошки"])
        finally:
            tasks_module.TaskHandler = TaskHandler
            tasks_module.TextToSpeech = real_tts
        out = capsys.readouterr().out
        assert code == 0
        assert "task: убраться у кошки" in out
        assert "task_id: task-9" in out
        assert voiced == ["Готово"]

    def test_main_create_empty_phrase(self, capsys):
        """Пустая фраза после триггера — код 3."""
        import lib.tasks as tasks_module
        tasks_module.TaskHandler = lambda google=None: TaskHandler(
            google=google or self._google_create())
        try:
            code = main(["create", "создай задачу"])
        finally:
            tasks_module.TaskHandler = TaskHandler
        assert code == 3

    def test_main_create_no_auth(self, capsys):
        """Нет авторизации Tasks — код 3."""
        import lib.tasks as tasks_module
        noauth = self._google_create(auth=False)
        tasks_module.TaskHandler = lambda google=None: TaskHandler(
            google=noauth)
        try:
            code = main(["create", "создай задачу купить хлеб"])
        finally:
            tasks_module.TaskHandler = TaskHandler
        out = capsys.readouterr().out
        assert code == 3
        assert "авторизации" in out

    def test_main_create_api_failure(self, capsys):
        """API вернуло None — код 1."""
        import lib.tasks as tasks_module
        tasks_module.TaskHandler = lambda google=None: TaskHandler(
            google=google or self._google_create(task_id=None))
        try:
            code = main(["create", "создай задачу купить хлеб"])
        finally:
            tasks_module.TaskHandler = TaskHandler
        assert code == 1

    def test_main_unknown_subcommand(self, capsys):
        """Неизвестная подкоманда — usage, код 2."""
        assert main(["удали", "что-то"]) == 2
        assert "usage" in capsys.readouterr().out
