"""Тесты перезапуска OmniRouter (`lib/monitor/omni.py::restart`).

Отдельный файл от test_omni_process.py (лимит 200 строк на файл, §9). CLI
подменяется на уровне `subprocess.run`, порт — на `omni.is_listening`: живого
прокси здесь не трогаем.
"""
import subprocess

from lib.monitor import omni


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _cli(monkeypatch, run=None, listening=True):
    """CLI считается найденным; `run` — чем отвечаем на вызов subprocess."""
    monkeypatch.setattr(omni.shutil, "which",
                        lambda name: {"node": "node",
                                      "omniroute": "omniroute"}.get(name))
    monkeypatch.setattr(omni, "entry_path", lambda: "entry.mjs")
    monkeypatch.setattr(omni, "is_listening", lambda url: listening)
    monkeypatch.setattr(subprocess, "run", run or (lambda argv, **kw: _Proc()))


def test_restart_stops_then_serves_detached(monkeypatch):
    # Регресс: `omniroute restart --daemon` не существует (Commander: «unknown
    # option», rc=1), а без --daemon restart поднимает сервер в foreground и
    # никогда не возвращается. Поэтому reset = `stop` + `serve --daemon`.
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv[-4:], kwargs["timeout"]))
        return _Proc(out="OmniRoute started in background (PID: 4242)\n")

    _cli(monkeypatch, _fake_run)
    ok, detail = omni.restart(20128)
    assert ok is True
    assert calls[0][0][-1] == "stop"
    assert calls[1][0] == ["serve", "--daemon", "--port", "20128"]
    assert "порт :20128" in detail and "background" in detail


def test_restart_stop_failure_does_not_block_start(monkeypatch):
    # Процесс мог упасть сам — тогда `stop` ничем не помогает, но поднять
    # сервер всё равно надо.
    seen = []

    def _fake_run(argv, **kwargs):
        seen.append(argv[-1])
        return _Proc(1) if argv[-1] == "stop" else _Proc(out="started")

    _cli(monkeypatch, _fake_run)
    ok, detail = omni.restart(20128)
    assert ok is True
    assert seen == ["stop", "20128"]


def test_restart_requires_open_port(monkeypatch):
    # rc=0 у CLI значит лишь «spawn случился»; порт не открылся — сервер не
    # поднялся, и врать про это в панели нельзя.
    _cli(monkeypatch, listening=False)
    monkeypatch.setattr(omni.time, "sleep", lambda s: None)
    ok, detail = omni.restart(20128, up_wait_s=0.1)
    assert ok is False
    assert "порт" in detail and "не открылся" in detail


def test_restart_reports_cli_failure(monkeypatch):
    _cli(monkeypatch,
         lambda argv, **kw: _Proc(1, err="error: unknown option '--port'"))
    ok, detail = omni.restart(None)
    assert ok is False
    assert "unknown option" in detail


def test_restart_without_cli_is_not_a_crash(monkeypatch):
    monkeypatch.setattr(omni.shutil, "which", lambda name: None)
    ok, detail = omni.restart()
    assert ok is False
    assert "не найден" in detail


def test_restart_timeout_is_reported(monkeypatch):
    _cli(monkeypatch)

    def _slow(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", _slow)
    ok, detail = omni.restart(20128, stop_timeout_s=5)
    assert ok is False
    assert "не завершился" in detail
