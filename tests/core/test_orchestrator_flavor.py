"""Тесты миксина «оживления» ответа (OrchestratorFlavorMixin)."""

from lib.core.orchestrator import Orchestrator


def _orch(mocker, llm=None, prompt_text="о"):
    """Оркестратор с flavor-секцией: включён, tmp-шаблон, заданный llm."""
    orch = Orchestrator(
        matcher=mocker.MagicMock(),
        output=mocker.MagicMock(),
        tts=mocker.MagicMock(),
        llm=llm,
    )
    orch._flavor_enabled = True
    orch._flavor_max_len = 120
    orch._flavor_timeout_s = 5
    orch._flavor_wait_s = 0.0
    orch._flavor_busy = False
    return orch


def _run_thread_inline(mocker):
    """Patch Thread так, чтобы target(args) выполнялся синхронно на start()."""
    def _factory(target=None, args=(), daemon=None, **kwargs):
        class _T:
            def start(self_inner):
                target(*args)
        return _T()
    return mocker.patch(
        "lib.core.orchestrator_flavor.threading.Thread", side_effect=_factory)


class TestMaybeFlavorGuards:
    """Когда добавка НЕ должна запускаться."""

    def test_noop_when_disabled(self, mocker):
        llm = mocker.MagicMock()
        orch = _orch(mocker, llm=llm)
        orch._flavor_enabled = False
        started = _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "ответ")
        started.assert_not_called()

    def test_noop_when_empty_response(self, mocker):
        orch = _orch(mocker, llm=mocker.MagicMock())
        started = _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "   ")
        started.assert_not_called()

    def test_noop_when_no_llm(self, mocker):
        orch = _orch(mocker, llm=None)
        started = _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "ответ")
        started.assert_not_called()

    def test_noop_when_busy(self, mocker):
        orch = _orch(mocker, llm=mocker.MagicMock())
        orch._flavor_busy = True
        started = _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "ответ")
        started.assert_not_called()

    def test_noop_when_template_missing(self, mocker):
        orch = _orch(mocker, llm=mocker.MagicMock())
        orch._flavor_prompt_path = "prompts/__nope__.txt"
        started = _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "ответ")
        started.assert_not_called()


class TestFlavorFlow:
    """Успешный путь: генерация фразы и вставка в канал."""

    def _orch_with_template(self, mocker, llm, tmp_path):
        p = tmp_path / "tpl.txt"
        p.write_text("q={command} a={response}", encoding="utf-8")
        orch = _orch(mocker, llm=llm)
        orch._flavor_prompt_path = str(p)
        return orch

    def test_voice_path_speaks_phrase(self, mocker, tmp_path):
        llm = mocker.MagicMock()
        llm.classify.return_value = "Успехов! и не забудь"
        orch = self._orch_with_template(mocker, llm, tmp_path)
        speak = mocker.patch.object(orch, "_speak_async")
        orch._speaking = False
        _run_thread_inline(mocker)
        orch._maybe_flavor("задача", "сделано")
        speak.assert_called_once_with("Успехов!")
        assert orch._flavor_busy is False

    def test_chat_path_sends_to_sink(self, mocker, tmp_path):
        llm = mocker.MagicMock()
        llm.classify.return_value = "Приятного аппетита"
        orch = self._orch_with_template(mocker, llm, tmp_path)
        sink = mocker.MagicMock()
        _run_thread_inline(mocker)
        orch._maybe_flavor("завтрак", "вкусно", sink=sink)
        sink.assert_called_once_with("\nПриятного аппетита")

    def test_classify_error_is_swallowed(self, mocker, tmp_path):
        llm = mocker.MagicMock()
        llm.classify.side_effect = RuntimeError("boom")
        orch = self._orch_with_template(mocker, llm, tmp_path)
        speak = mocker.patch.object(orch, "_speak_async")
        _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "ответ")
        speak.assert_not_called()
        assert orch._flavor_busy is False

    def test_empty_phrase_does_not_emit(self, mocker, tmp_path):
        llm = mocker.MagicMock()
        llm.classify.return_value = "   "
        orch = self._orch_with_template(mocker, llm, tmp_path)
        emit = mocker.patch.object(orch, "_emit_flavor")
        _run_thread_inline(mocker)
        orch._maybe_flavor("cmd", "ответ")
        emit.assert_not_called()


class TestEmitFlavor:
    """Вставка фразы: уважение к озвучке и стоп-слову."""

    def test_skip_when_abort_set(self, mocker):
        import threading
        orch = _orch(mocker, llm=mocker.MagicMock())
        orch._abort_playback = threading.Event()
        orch._abort_playback.set()
        speak = mocker.patch.object(orch, "_speak_async")
        orch._emit_flavor("фраза", None)
        speak.assert_not_called()

    def test_wait_idle_timeout_skips(self, mocker):
        orch = _orch(mocker, llm=mocker.MagicMock())
        orch._flavor_wait_s = 0.0
        orch._speaking = True
        speak = mocker.patch.object(orch, "_speak_async")
        orch._emit_flavor("фраза", None)
        speak.assert_not_called()


class TestInitFlavor:
    """Чтение секции flavor с дефолтами и защитой от не-словаря."""

    def test_defaults_when_matcher_returns_mock(self, mocker):
        orch = Orchestrator(
            matcher=mocker.MagicMock(), output=mocker.MagicMock(),
            tts=mocker.MagicMock())
        # MagicMock-матчер -> не-словарь -> дефолты
        assert orch._flavor_enabled is True
        assert orch._flavor_max_len == 120
        assert orch._flavor_busy is False

    def test_reads_config_values(self, mocker):
        matcher = mocker.MagicMock()
        matcher.get_flavor_config.return_value = {
            "enabled": False, "max_len": 40, "timeout_s": 3,
            "prompt": "x/y.txt"}
        orch = Orchestrator(
            matcher=matcher, output=mocker.MagicMock(),
            tts=mocker.MagicMock())
        assert orch._flavor_enabled is False
        assert orch._flavor_max_len == 40
        assert orch._flavor_timeout_s == 3
        assert orch._flavor_prompt_path == "x/y.txt"
