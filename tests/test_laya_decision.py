"""Тесты decision-слоя Laya: клиент и путь оркестратора."""

import json
from lib.laya_decision import LayaDecision
from lib.orchestrator import Orchestrator
CONFIG = {
    "url": "http://127.0.0.1:8080",
    "threshold": 0.5,
    "timeout": 5,
    "criteria": {
        "volumeup": "сделать громче",
        "volumedown": "сделать тише",
        "stop": "остановить музыку",
    },
}


class FakeResponse:
    """Файлоподобный ответ urllib с контекст-менеджером."""

    def __init__(self, payload=None, status=200):
        self._payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _make_client(config=None):
    return LayaDecision(config or CONFIG)


def _ok_answer(choice, confidence):
    return {"command": {"type": "choice", "choice": choice,
                        "confidence": confidence}}


class TestLayaDecisionDetect:
    def test_detects_command_above_threshold(self, mocker):
        """Уверенная известная команда возвращается с confidence."""
        client = _make_client()

        def fake_urlopen(url_or_req, timeout=None):
            path = url_or_req if isinstance(url_or_req, str) else url_or_req.full_url
            if path.endswith("/health"):
                return FakeResponse()
            return FakeResponse({"answers": _ok_answer("volumeup", 0.9),
                                 "usage": {"input_tokens": 5, "latency_ms": 30}})

        mocker.patch("lib.laya_decision.urllib.request.urlopen",
                     side_effect=fake_urlopen)
        assert client.detect("алиса сделай громче") == ("volumeup", 0.9)

    def test_none_choice_returns_none(self, mocker):
        """Диалог без команды (`none`) не исполняется."""
        client = _make_client()

        def fake_urlopen(url_or_req, timeout=None):
            if isinstance(url_or_req, str):
                return FakeResponse()
            return FakeResponse({"answers": _ok_answer("none", 0.9)})

        mocker.patch("lib.laya_decision.urllib.request.urlopen",
                     side_effect=fake_urlopen)
        assert client.detect("как дела") is None

    def test_below_threshold_returns_none(self, mocker):
        """Уверенность ниже порога — команда не запускается."""
        client = _make_client()

        def fake_urlopen(url_or_req, timeout=None):
            if isinstance(url_or_req, str):
                return FakeResponse()
            return FakeResponse({"answers": _ok_answer("stop", 0.2)})

        mocker.patch("lib.laya_decision.urllib.request.urlopen",
                     side_effect=fake_urlopen)
        assert client.detect("выключи") is None

    def test_unknown_choice_returns_none(self, mocker):
        """Выбранный кандидат вне критериев конфига игнорируется."""
        client = _make_client()

        def fake_urlopen(url_or_req, timeout=None):
            if isinstance(url_or_req, str):
                return FakeResponse()
            return FakeResponse({"answers": _ok_answer("launch_missile", 0.99)})

        mocker.patch("lib.laya_decision.urllib.request.urlopen",
                     side_effect=fake_urlopen)
        assert client.detect("что-то странное") is None

    def test_server_down_returns_none(self, mocker):
        """Недоступный сервер — тихий None, без исключений."""
        client = _make_client()
        mocker.patch("lib.laya_decision.urllib.request.urlopen",
                     side_effect=OSError("refused"))
        assert client.detect("алиса стоп") is None

    def test_criteria_always_include_none(self):
        """В критерии добавляется `none`, если его не задали."""
        client = _make_client()
        assert "none" in client._criteria

    def test_close_terminates_launched_server(self, mocker):
        """close() останавливает запущенный нами сервер."""
        client = _make_client()
        proc = mocker.MagicMock()
        client._proc = proc
        client.close()
        proc.terminate.assert_called_once_with()


class TestOrchestratorDecisionPath:
    """Оркестратор с decision: Laya вместо intent/opencode."""

    def _make(self, mocker, decision):
        matcher = mocker.MagicMock()
        matcher.find_command.return_value = (None, [], False)
        matcher.missing_requires.return_value = []
        matcher.has_trigger.return_value = True
        matcher.status_snapshot.return_value = {}
        matcher.requires_map.return_value = {}
        orch = Orchestrator(
            matcher=matcher,
            output=mocker.MagicMock(),
            tts=mocker.MagicMock(),
            decision=decision,
        )
        return orch, matcher

    def test_decision_command_executed(self, mocker):
        """Laya распознала команду → выполняется, intent не зовётся."""
        decision = mocker.MagicMock()
        decision.detect.return_value = ("stop", 0.9)
        orch, matcher = self._make(mocker, decision)
        matcher.execute_by_id.return_value = True
        orch.process_text("алиса стоп")
        matcher.execute_by_id.assert_called_once_with("stop")
        orch._output.print_text.assert_any_call("алиса стоп")
        orch._output.print_text.assert_any_call("stop")
        orch._output.print_info.assert_any_call(
            "[Decision] Лайя: команда распознана «stop» (c=0.90)")
        orch._opencode_queue.empty()

    def test_decision_none_stubs_omni_and_stops(self, mocker):
        """Laya неуверенна → заглушка OmniRouter, opencode не вызывается."""
        decision = mocker.MagicMock()
        decision.detect.return_value = None
        orch, matcher = self._make(mocker, decision)
        orch.process_text("да блин какая же ты тупая")
        matcher.execute_by_id.assert_not_called()
        orch._output.print_info.assert_any_call(
            "[Decision] Лайя: команда не распознана — запрос ушёл бы "
            "в OmniRouter (auto/fast), пока пропускаем")
        # legacy-путь не используется: intent пуст, opencode не звался
        assert orch._intent is None
        orch._opencode_queue.empty()

    def test_decision_blocked_reports_and_returns(self, mocker):
        """Заблокированная команда Laya сообщается, intent не зовётся."""
        decision = mocker.MagicMock()
        decision.detect.return_value = ("stop", 0.8)
        orch, matcher = self._make(mocker, decision)
        matcher.execute_by_id.return_value = False
        matcher.missing_requires.return_value = ["media_session"]
        matcher.need_message.return_value = "Нужен статус: media_session"
        orch.process_text("алиса выключи")
        matcher.execute_by_id.assert_called_once_with("stop")
        orch._output.print_error.assert_called()
        orch._opencode_queue.empty()

    def test_decision_unknown_command_errors(self, mocker):
        """Выбранная Laya команда отсутствует в matcher — ошибка, return."""
        decision = mocker.MagicMock()
        decision.detect.return_value = ("nonexistent", 0.99)
        orch, matcher = self._make(mocker, decision)
        matcher.execute_by_id.return_value = False
        matcher.missing_requires.return_value = []
        orch.process_text("алиса что-нибудь")
        orch._output.print_error.assert_called_once_with(
            "[Decision] Команда «nonexistent» не найдена")
        orch._opencode_queue.empty()

    def test_legacy_path_without_decision_still_works(self, mocker):
        """Без decision включённый intent остаётся рабочим фолбэком."""
        intent = mocker.MagicMock()
        intent.detect.return_value = "volumeup"
        orch, matcher = self._make(mocker, decision=None)
        orch._intent = intent
        matcher.execute_by_id.return_value = True
        orch.process_text("алиса сделай громче")
        intent.detect.assert_called_once()
        matcher.execute_by_id.assert_called_once_with("volumeup")
