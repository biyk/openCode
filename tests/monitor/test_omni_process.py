"""Тесты проб OmniRouter (`lib/monitor/omni.py`).

Живой процесс тут не нужен: сеть подменяется на уровне `http_ok` и
`socket.create_connection`, CLI — на уровне `shutil.which`. Перезапуск
(сам CLI и его аргументы) — в test_omni_restart.py.
"""
import socket

from lib.monitor import omni
from lib.monitor.tuning import (MONITOR_OMNI_HEALTH_TIMEOUT_S, MONITOR_OMNI_PORT,
                                MONITOR_OMNI_URL, MONITOR_PROBE_TIMEOUT_S)


def test_port_from_url_reads_explicit_port():
    assert omni.port_from_url("http://127.0.0.1:21000") == 21000


def test_port_from_url_falls_back_to_default():
    assert omni.port_from_url("http://localhost") == MONITOR_OMNI_PORT
    assert omni.port_from_url("localhost:22000") == 22000


def test_is_healthy_uses_health_endpoint(monkeypatch):
    seen = {}

    def _fake(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return True

    monkeypatch.setattr(omni, "http_ok", _fake)
    assert omni.is_healthy("http://127.0.0.1:20128/") is True
    assert seen["url"] == "http://127.0.0.1:20128/api/health"
    # Общий таймаут проб (1 с) слишком тесный для /api/health под нагрузкой:
    # спотыкаясь о него, смотритель считал здоровый прокси зависшим.
    assert seen["timeout"] == MONITOR_OMNI_HEALTH_TIMEOUT_S
    assert MONITOR_OMNI_HEALTH_TIMEOUT_S > MONITOR_PROBE_TIMEOUT_S


def test_is_healthy_false_when_endpoint_silent(monkeypatch):
    monkeypatch.setattr(omni, "http_ok", lambda url, timeout: False)
    assert omni.is_healthy() is False


def test_is_listening_true_when_port_opens(monkeypatch):
    class _Sock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, timeout=None: _Sock())
    assert omni.is_listening(MONITOR_OMNI_URL) is True


def test_is_listening_false_when_port_refused(monkeypatch):
    def _boom(addr, timeout=None):
        raise ConnectionRefusedError("порт закрыт")

    monkeypatch.setattr(socket, "create_connection", _boom)
    assert omni.is_listening() is False


def test_cli_argv_prefers_node_entry(monkeypatch):
    monkeypatch.setattr(omni.shutil, "which",
                        lambda name: {"node": r"C:\node.exe",
                                      "omniroute": r"C:\npm\omniroute.cmd",
                                      }.get(name))
    monkeypatch.setattr(omni, "entry_path", lambda: r"C:\npm\entry.mjs")
    assert omni.cli_argv(["restart", "--daemon"]) == [
        r"C:\node.exe", r"C:\npm\entry.mjs", "restart", "--daemon"]


def test_cli_argv_falls_back_to_cmd_shim(monkeypatch):
    monkeypatch.setattr(omni.shutil, "which",
                        lambda name: (r"C:\npm\omniroute.cmd"
                                      if name == "omniroute" else None))
    monkeypatch.setattr(omni, "entry_path", lambda: None)
    assert omni.cli_argv(["health"]) == [
        "cmd.exe", "/d", "/c", r"C:\npm\omniroute.cmd", "health"]


def test_cli_argv_none_without_package(monkeypatch):
    monkeypatch.setattr(omni.shutil, "which", lambda name: None)
    assert omni.cli_argv(["health"]) is None


def test_entry_path_none_when_shim_missing(monkeypatch):
    monkeypatch.setattr(omni.shutil, "which", lambda name: None)
    assert omni.entry_path() is None
