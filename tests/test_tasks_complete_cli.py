"""Тесты задач: CLI complete/create."""


import base64
from lib.tasks import TaskHandler, _decode_arg, main


class TestCompleteCli:
    """Команды complete/create, _decode_arg."""

    def _google(self):
        tasks = [{"id": "t1", "title": "подчинить лампочку в ванной",
                  "status": "needsAction"}]
        return type("G", (), {
            "list_tasks": lambda self, show_completed=False: tasks,
            "complete_task": lambda self, task_id: {"status": "completed"},
        })()

    def _google_create(self, task_id="task-9", auth=True, existing=None, fail_list=False):
        from lib.google_tasks import GoogleOAuthError

        class G:
            def create_task(self, title, notes=None):
                G.created.append(title)
                return task_id

            def list_tasks(self, show_completed=False):
                if fail_list:
                    raise RuntimeError("network down")
                return list(existing or [])

            def is_ready(self):
                return auth

            def authorize(self):
                if not auth:
                    raise GoogleOAuthError("нет consent")
        G.created = []
        return G()

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

    def _main_create(self, monkeypatch, g, phrase, laya="keep", speak=False):
        """CLI create с подменой обработчика; laya/speak — заглушки."""
        import lib.tasks as tasks_module
        monkeypatch.setattr(tasks_module, "TaskHandler",
                            lambda google=None: TaskHandler(google=g))
        if laya != "keep":
            monkeypatch.setattr(tasks_module, "get_laya_decision", lambda: laya)
        if speak:
            monkeypatch.setattr(tasks_module, "TextToSpeech", lambda *a, **k: (
                type("T", (), {"speak_and_play": lambda self, t: None})()))
        return main(["create", phrase])

    def test_main_create_duplicate_exact_skips(self, monkeypatch, capsys):
        """Строгий дубликат в списке — создание пропускаем, код 0."""
        g = self._google_create(
            existing=[{"id": "1", "title": "убраться у кошки"}])
        code = self._main_create(monkeypatch, g, "создай задачу убраться у кошки")
        out = capsys.readouterr().out
        assert code == 0
        assert '"method": "exact"' in out
        assert g.created == []

    def test_main_create_duplicate_laya_skips(self, monkeypatch, capsys):
        """Laya сводит новую фразу к существующей задаче — пропускаем."""
        fake = type("D", (), {"detect": lambda s, text, **kw: ("помыть полы", 0.9, 0.1)})()
        g = self._google_create(existing=[{"id": "1", "title": "помыть полы"}])
        code = self._main_create(monkeypatch, g, "создай задачу вымыть пол",
                                 laya=fake)
        out = capsys.readouterr().out
        assert code == 0
        assert '"method": "laya"' in out
        assert '"score": 0.9' in out and "(laya, c=0.90)" in out
        assert g.created == []

    def test_main_create_dedup_error_still_creates(self, monkeypatch, capsys):
        """Ошибка списка задач не блокирует создание."""
        g = self._google_create(fail_list=True)
        code = self._main_create(monkeypatch, g, "создай задачу купить хлеб",
                                 laya=None, speak=True)
        out = capsys.readouterr().out
        assert code == 0
        assert g.created == ["купить хлеб"]
        assert "task_id: task-9" in out

    def test_main_unknown_subcommand(self, capsys):
        """Неизвестная подкоманда — usage, код 2."""
        assert main(["удали", "что-то"]) == 2
        assert "usage" in capsys.readouterr().out
