"""Тесты точки входа доски (`lib/voice_cmd/knowledge_review.py`).

Важно для монитора: `launch(port, fragment)` открывает страницу с якорем
вкладки — без него браузер показывает ту вкладку, что помнит, а не «Сервисы».
"""

from lib.voice_cmd import knowledge_review as kr


def _fake_open(monkeypatch, calls):
    import lib.browser_control as bc

    monkeypatch.setattr(bc, "open_url",
                        lambda url, *a, **k: calls.append(url) or True)


def test_open_page_without_fragment_is_plain_root(monkeypatch):
    calls = []
    _fake_open(monkeypatch, calls)
    kr.open_page(8765)
    assert calls == ["http://127.0.0.1:8765/"]


def test_open_page_appends_tab_fragment(monkeypatch):
    calls = []
    _fake_open(monkeypatch, calls)
    kr.open_page(8765, "services")
    assert calls == ["http://127.0.0.1:8765/#services"]


def test_launch_passes_fragment_when_server_up(monkeypatch):
    calls = []
    _fake_open(monkeypatch, calls)
    monkeypatch.setattr(kr, "is_up", lambda port: True)
    monkeypatch.setattr(kr, "commands_file", lambda: "commands.json")
    monkeypatch.setattr(kr, "load_review", lambda cfile: {"port": 8765})
    assert kr.launch(fragment="services") == 0
    assert calls == ["http://127.0.0.1:8765/#services"]


def test_launch_raises_server_when_down(monkeypatch):
    spawned = []
    calls = []
    _fake_open(monkeypatch, calls)
    state = {"up": False}

    def _is_up(port):
        return state["up"]

    def _spawn(port):
        spawned.append(port)
        state["up"] = True

    monkeypatch.setattr(kr, "is_up", _is_up)
    monkeypatch.setattr(kr, "spawn_server", _spawn)
    monkeypatch.setattr(kr, "commands_file", lambda: "commands.json")
    monkeypatch.setattr(kr, "load_review", lambda cfile: {"port": 8765})
    assert kr.launch(8899, "services") == 0
    assert spawned == [8899]
    assert calls == ["http://127.0.0.1:8899/#services"]


def test_launch_reports_dead_server(monkeypatch):
    calls = []
    _fake_open(monkeypatch, calls)
    monkeypatch.setattr(kr, "is_up", lambda port: False)
    monkeypatch.setattr(kr, "spawn_server", lambda port: None)
    monkeypatch.setattr(kr, "UP_WAIT_S", 0.1)
    monkeypatch.setattr(kr, "commands_file", lambda: "commands.json")
    monkeypatch.setattr(kr, "load_review", lambda cfile: {})
    assert kr.launch(8765, "services") == 1
    assert calls == []          # страницу не открываем, если сервер лежит


def test_cli_launch_uses_default_fragment(monkeypatch):
    seen = {}

    def _launch(port=None, fragment=""):
        seen["port"] = port
        seen["fragment"] = fragment
        return 0

    monkeypatch.setattr(kr, "launch", _launch)
    assert kr.main(["launch"]) == 0
    assert seen == {"port": None, "fragment": ""}


def test_cli_launch_tab_passthrough(monkeypatch):
    # Ручная проверка монитора: `launch --tab services` ведёт на вкладку;
    # вести «#» не нужно — open_page дописывает её сама.
    seen = {}

    def _launch(port=None, fragment=""):
        seen["port"] = port
        seen["fragment"] = fragment
        return 0

    monkeypatch.setattr(kr, "launch", _launch)
    assert kr.main(["--port", "8899", "launch", "--tab", "#services"]) == 0
    assert seen == {"port": 8899, "fragment": "services"}
