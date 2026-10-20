# TOOLTIP: Тесты пробы вкладок cdp_probe: короткое ожидание, ранний выход, молчащие вкладки
"""Тесты lib/browser/cdp_probe.py: как вкладка опрашивается и что считается
ответом, плюс сквозной потолок ответа в cdp_client. Выбор вкладки для
сдвига скорости — в test_playback_rate.py, CLI — в test_playback_rate_cli.py.
"""

import json
from unittest.mock import MagicMock

import pytest

from lib.browser import cdp_client as cdc
from lib.browser import cdp_probe as cp
from lib.core.tuning import CDP_PAGE_LOAD_S, CDP_PROBE_S

TAB = {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/1"}


def _tab(tab_id: str, title: str = "Ролик") -> dict:
    return {"id": tab_id, "type": "page", "title": title,
            "url": f"https://site.test/{tab_id}"}


class Pages:
    """Заглушка eval_js/_list_tabs: вкладки, их плееры и ответы по таймауту.

    Отдельно считает пробы каждой вкладки — по нему видно, что обход
    прекратился раньше, чем добрался до конца списка.
    """

    def __init__(self, tabs: list, states: dict) -> None:
        self.tabs = tabs
        self.states = states
        self.probed: list[str] = []
        self.timeouts: list[float] = []

    def list_tabs(self, port: int = cdc.DEFAULT_PORT) -> list:
        return self.tabs

    def eval_js(self, tab: dict, script: str,
                timeout: float = CDP_PAGE_LOAD_S) -> tuple[bool, object]:
        self.probed.append(tab["id"])
        self.timeouts.append(timeout)
        st = self.states[tab["id"]]
        if st.get("error"):
            return False, "Connection timed out"
        if "var delta" in script:               # применение сдвига — не проба
            return True, {}
        return True, {"playing": st.get("playing", False),
                      "audible": st.get("audible", False),
                      "rate": st.get("rate", 0)}


@pytest.fixture
def pages(mocker):
    """Ставит заглушку на CDP-клиент; возврат — сам объект заглушки."""
    def install(tabs: list, states: dict) -> Pages:
        fake = Pages(tabs, states)
        mocker.patch.object(cdc, "_list_tabs", fake.list_tabs)
        mocker.patch.object(cdc, "eval_js", fake.eval_js)
        return fake
    return install


class TestProbeJs:
    """Содержание JS-пробы: она и отличает «играет» от «тихо».

    Проба обязана быть одним выражением без завершающих `()` — иначе на
    странице `TypeError: (intermediate value) is not a function` (§4.5).
    """

    def test_guards_state_and_sound(self):
        probe = cp.probe_js()
        for check in ("m.paused", "m.ended", "m.readyState < 2",
                      "m.muted", "m.volume > 0"):
            assert check in probe
        assert probe.startswith("(function(){")
        assert probe.endswith("})()")


class TestClientTimeout:
    """Контракт cdp_client: потолок ответа вкладки — параметр, не жёсткие 30 с.

    Раньше `timeout=30` сидел в `_ws_for` и держал и соединение, и каждый
    `recv`: обход всех вкладок складывался в минуту молчания микрофона.
    """

    def _conn(self, mocker):
        ws = MagicMock()
        ws.recv.return_value = json.dumps({"id": 1, "result": {}})
        return mocker.patch.object(
            cdc.websocket, "create_connection", return_value=ws)

    def test_timeout_goes_to_websocket(self, mocker):
        conn = self._conn(mocker)
        cdc.eval_js(TAB, "1+1", timeout=4.0)
        assert conn.call_args.kwargs["timeout"] == 4.0

    def test_default_is_the_page_ceiling(self, mocker):
        conn = self._conn(mocker)
        cdc.eval_js(TAB, "1+1")
        assert conn.call_args.kwargs["timeout"] == CDP_PAGE_LOAD_S


class TestEvalTab:
    """Как вкладка опрашивается и что считается ответом."""

    def test_probe_uses_short_timeout(self, pages):
        """Регресс 62-секундной команды: пробу ждём CDP_PROBE_S, не 30 с."""
        fake = pages([_tab("a")], {"a": {"playing": False}})
        cp.eval_tab(fake.tabs[0], cp.probe_js())
        assert fake.timeouts == [CDP_PROBE_S]

    def test_no_answer_is_empty_dict(self, pages):
        """Не ответила — пустой словарь: «не слышим» отличимо от «не играет»."""
        fake = pages([_tab("d")], {"d": {"error": True}})
        assert cp.eval_tab(fake.tabs[0], cp.probe_js()) == {}


class TestPageTabs:
    """Фильтр вкладок: опрашиваем только обычные страницы."""

    def test_skips_workers_and_extensions(self, pages):
        sw = {"id": "s", "type": "service_worker", "url": "https://a/sw.js"}
        bg = {"id": "b", "type": "background_page", "url": "https://a/bg.html"}
        fake = pages([_tab("p"), sw, bg], {"p": {"playing": False}})
        assert [t["id"] for t in cp.page_tabs()] == ["p"]
        cp.sounding(cp.page_tabs())
        assert fake.probed == ["p"]


class TestSounding:
    """Обход вкладок: кого выбрать, когда встать и кого записать в молчащих."""

    def test_audible_tab_stops_the_sweep(self, pages):
        """Звучащая вкладка найдена — остальные не пробираем вовсе."""
        states = {"a": {"playing": True, "audible": True, "rate": 1.0},
                  "b": {"playing": True, "audible": True, "rate": 1.0}}
        fake = pages([_tab("a"), _tab("b")], states)
        scan = cp.sounding(cp.page_tabs())
        assert scan.tab["id"] == "a" and scan.dead == 0
        assert fake.probed == ["a"]

    def test_muted_tab_does_not_end_the_sweep(self, pages):
        """Заглушённая играющая вкладка — candidate, но ищем звучащую дальше."""
        states = {"m": {"playing": True, "audible": False, "rate": 1.0},
                  "l": {"playing": True, "audible": True, "rate": 1.0}}
        fake = pages([_tab("m"), _tab("l")], states)
        scan = cp.sounding(cp.page_tabs())
        assert scan.tab["id"] == "l" and scan.others == 1
        assert fake.probed == ["m", "l"]

    def test_only_muted_tabs_returns_first(self, pages):
        """Звучащих нет — остаётся первая играющая (порядок браузера)."""
        playing = {"playing": True, "audible": False, "rate": 1.0}
        states = {"m": playing, "n": playing}
        fake = pages([_tab("m"), _tab("n")], states)
        scan = cp.sounding(cp.page_tabs())
        assert scan.tab["id"] == "m" and scan.others == 1
        assert fake.probed == ["m", "n"]

    def test_dead_tabs_counted_separately(self, pages):
        """Молчаливые вкладки — в dead: тишина в них не доказана."""
        states = {"d": {"error": True}, "i": {"playing": False}}
        pages([_tab("d"), _tab("i")], states)
        scan = cp.sounding(cp.page_tabs())
        assert scan.tab is None and scan.dead == 1 and scan.others == 0

    def test_no_tabs_at_all_is_not_dead(self, pages):
        """Вкладок нет вовсе — это тишина, а не зависший браузер."""
        pages([], {})
        scan = cp.sounding(cp.page_tabs())
        assert scan.tab is None and scan.dead == 0
