# TOOLTIP: Тесты поиска звучащей вкладки и сдвига скорости видео (playback_rate)
"""Тесты lib/browser/playback_rate.py: какая вкладка считается звучащей и
как сдвигается её скорость. CDP заглушён целиком; WebSocket-слой — в
test_cdp_events.py, CLI и проводка команд — в test_playback_rate_cli.py.
"""

import pytest

from lib.browser import playback_rate as pr


def _tab(tab_id: str, title: str = "Ролик") -> dict:
    return {"id": tab_id, "type": "page", "title": title,
            "url": f"https://site.test/{tab_id}"}


class Cdp:
    """Заглушка eval_js/_list_tabs: вкладки с состоянием их плееров.

    Проба читает playing/audible/rate, применение сдвигает rate в тех же
    границах, что и JS: тест держит контракт модуля, а не движок браузера.
    """

    def __init__(self, tabs: list, states: dict) -> None:
        self.tabs = tabs
        self.states = states
        self.scripts: list[str] = []

    def list_tabs(self, port: int = pr.DEFAULT_PORT) -> list:
        return self.tabs

    def eval_js(self, tab: dict, script: str) -> tuple[bool, object]:
        self.scripts.append(script)
        st = self.states[tab["id"]]
        if st.get("error"):
            return False, "нет webSocketDebuggerUrl"
        if "var delta" not in script:            # проба состояния
            return True, {"playing": st.get("playing", False),
                          "audible": st.get("audible", False),
                          "rate": st.get("rate", 0)}
        if st.get("drop"):                       # вкладка замолчала
            return True, {"playing": False, "count": 0, "before": 0,
                          "after": 0}
        before = st["rate"]
        delta = float(script.split("var delta = ")[1].split(";")[0])
        st["rate"] = min(pr.RATE_MAX, max(pr.RATE_MIN, before + delta))
        return True, {"playing": True, "count": 1, "before": before,
                      "after": st["rate"]}


@pytest.fixture
def cdp(mocker):
    """Ставит заглушку на CDP-клиент; возврат — сам объект заглушки."""
    def install(tabs: list, states: dict) -> Cdp:
        fake = Cdp(tabs, states)
        mocker.patch("lib.browser.cdp_client._list_tabs", fake.list_tabs)
        mocker.patch("lib.browser.cdp_client.eval_js", fake.eval_js)
        return fake
    return install


class TestSoundingTabs:
    """Как именно ищется вкладка, которая звучит."""

    def test_audible_tab_wins(self, cdp):
        """Заглушённая вкладка не мешает: первой становится звучащая."""
        states = {"m": {"playing": True, "audible": False, "rate": 1.0},
                  "l": {"playing": True, "audible": True, "rate": 1.0}}
        cdp([_tab("m"), _tab("l")], states)
        assert [t["id"] for t, _ in pr.sounding_tabs()] == ["l", "m"]

    def test_paused_and_empty_tabs_skipped(self, cdp):
        """Пауза и страница без медиа — не кандидаты."""
        states = {"i": {"playing": False},
                  "p": {"playing": True, "audible": True, "rate": 1.0}}
        cdp([_tab("i"), _tab("p")], states)
        assert [t["id"] for t, _ in pr.sounding_tabs()] == ["p"]

    def test_service_worker_not_probed(self, cdp):
        """Service worker и фоновые страницы расширений не опрашиваются."""
        sw = {"id": "s", "type": "service_worker", "url": "https://a/sw.js"}
        states = {"p": {"playing": True, "audible": True, "rate": 1.0}}
        fake = cdp([_tab("p"), sw], states)
        pr.sounding_tabs()
        assert len(fake.scripts) == 1

    def test_tab_without_answer_skipped(self, cdp):
        """Вкладка не ответила (нет контекста) — пропускаем, не падаем."""
        states = {"d": {"error": True},
                  "a": {"playing": True, "audible": True, "rate": 1.0}}
        cdp([_tab("d"), _tab("a")], states)
        assert [t["id"] for t, _ in pr.sounding_tabs()] == ["a"]


class TestBumpRate:
    """Сдвиг скорости выбранной вкладки."""

    def test_up_and_down(self, cdp):
        """up поднимает скорость, down опускает; итог — в результате."""
        states = {"a": {"playing": True, "audible": True, "rate": 1.0}}
        cdp([_tab("a")], states)
        assert pr.bump_rate(0.05)["after"] == pytest.approx(1.05)
        assert pr.bump_rate(-0.1)["after"] == pytest.approx(0.95)

    def test_clamped_to_bounds(self, cdp):
        """Границы не пускают ниже неразборчивой и выше слушаемого."""
        cdp([_tab("a")], {"a": {"playing": True, "audible": True,
                                "rate": 0.28}})
        assert pr.bump_rate(-0.05)["after"] == pytest.approx(pr.RATE_MIN)
        cdp([_tab("a")], {"a": {"playing": True, "audible": True,
                                "rate": 4.0}})
        assert pr.bump_rate(0.05)["after"] == pytest.approx(pr.RATE_MAX)

    def test_nothing_playing(self, cdp):
        """Ни одного играющего элемента — команда не выполнена."""
        cdp([_tab("a")], {"a": {"playing": False}})
        res = pr.bump_rate(0.05)
        assert res["ok"] is False
        assert res["error"] == "ни одно видео не играет"

    def test_tab_stopped_between_probe_and_apply(self, cdp):
        """Ролик кончился между пробой и сдвигом — неуспех, а не тишина."""
        states = {"a": {"playing": True, "audible": True, "rate": 1.0,
                        "drop": True}}
        cdp([_tab("a")], states)
        assert pr.bump_rate(0.05)["ok"] is False

    def test_result_describes_choice(self, cdp):
        """В результате — вкладка, её скорость, глушение и молчаливые соседи."""
        states = {"a": {"playing": True, "audible": True, "rate": 1.0},
                  "b": {"playing": True, "audible": False, "rate": 1.0}}
        cdp([_tab("a"), _tab("b")], states)
        res = pr.bump_rate(0.05)
        assert res["title"] == "Ролик" and res["audible"] is True
        assert res["others"] == 1 and res["before"] == pytest.approx(1.0)

    def test_js_guards_state_and_bounds(self):
        """Проба отличает играющий элемент; сдвиг — одним блоком с clamp."""
        probe = pr._probe_js()
        for check in ("m.paused", "m.ended", "m.readyState < 2",
                      "m.muted", "m.volume > 0"):
            assert check in probe
        apply_js = pr._apply_js(-0.05)
        assert "var delta = -0.05;" in apply_js
        assert f"Math.max({pr.RATE_MIN}" in apply_js
        assert "playbackRate = rate" in apply_js
        assert apply_js.startswith("(function(){")
        assert apply_js.endswith("})()")


class TestReport:
    """Печать итога и компактные числа скорости."""

    def test_report_prints_rates(self, capsys):
        pr._report({"ok": True, "title": "Ролик", "before": 1.0,
                    "after": 0.95, "audible": False, "others": 2})
        out = capsys.readouterr().out
        assert "Ролик" in out and "1 → 0.95" in out
        assert "без звука" in out and "+2 играющих" in out

    def test_report_prints_error(self, capsys):
        pr._report({"ok": False, "error": "ни одно видео не играет"})
        assert "ни одно видео не играет" in capsys.readouterr().out

    def test_num_compact(self):
        assert pr._num(1.0) == "1" and pr._num(0.95) == "0.95"
        assert pr._num(None) == "None"
