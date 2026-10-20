"""Тесты перезапуска OmniRouter (`lib/monitor/omni.py::restart`).

Отдельный файл от test_omni_process.py (лимит 200 строк на файл, §9). CLI
подменяется на уровне `subprocess.run`, порт — на `omni.is_listening`: живого
прокси здесь не трогаем. Дренаж (правило 4) — после `stop` ждём, пока процесс
сам отдаст порт; не отдал — второй экземпляр не поднимаем (EADDRINUSE).
"""
import subprocess

from lib.monitor import omni


class _Proc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _cli(monkeypatch, run=None, listening=True, drain_closed=True):
    """CLI считается найденным; `run` — чем отвечаем на вызов subprocess.

    `is_listening` отвечает два раза: сначала дренажу (отдал ли порт), потом
    подъёму (открылся ли порт). Последнее значение — на все дальнейшие пробы.
    """
    monkeypatch.setattr(omni.shutil, "which",
                        lambda name: {"node": "node",
                                      "omniroute": "omniroute"}.get(name))
    monkeypatch.setattr(omni, "entry_path", lambda: "entry.mjs")
    seq = [not drain_closed, listening]

    def _listen(url):
        return seq.pop(0) if len(seq) > 1 else seq[-1]

    monkeypatch.setattr(omni, "is_listening", _listen)
    monkeypatch.setattr(omni.time, "sleep", lambda s: None)
    monkeypatch.setattr(subprocess, "run", run or (lambda argv, **kw: _Proc()))


def test_restart_stops_then_serves_detached(monkeypatch):
    # Регресс: `omniroute restart --daemon` не существует (Commander: «unknown
    # option», rc=1), а без --daemon restart поднимает сервер в foreground и
    # никогда не возвращается. Поэтому reset = `stop` + `serve --daemon`.
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append((argv[2:], kwargs["timeout"]))
        return _Proc(out="OmniRoute started in background (PID: 4242)\n")

    _cli(monkeypatch, _fake_run)
    ok, detail = omni.restart(20128)
    assert ok is True
    assert calls[0][0] == ["stop"]
    assert calls[1][0] == ["serve", "--daemon", "--port", "20128"]
    assert "порт :20128" in detail and "background" in detail


def test_restart_without_drain_never_calls_stop(monkeypatch):
    """Порта нет — процесс умер сам: `stop` звать нечего (правило 1)."""
    calls = []

    def _fake_run(argv, **kwargs):
        calls.append(argv[2:])
        return _Proc(out="started")

    _cli(monkeypatch, _fake_run)
    ok, detail = omni.restart(20128, drain=False)
    assert ok is True
    assert calls == [["serve", "--daemon", "--port", "20128"]]
    assert "порт :20128" in detail


def test_restart_waits_for_the_port_to_be_released(monkeypatch):
    """Дренаж: между `stop` и `serve` ждём, пока процесс сам отдаст порт."""
    events = []

    def _run(argv, **kwargs):
        events.append(argv[2])
        return _Proc()

    def _drain(url, wait_s, poll_s=1.0):
        events.append("drain")
        return True

    _cli(monkeypatch, _run)
    monkeypatch.setattr(omni, "wait_port_closed", _drain)
    ok, detail = omni.restart(20128)
    assert ok is True
    assert events == ["stop", "drain", "serve"]


def test_restart_refuses_second_instance_when_port_stays(monkeypatch):
    """Не дождались дренажа — не стартуем второй: гонка за порт (EADDRINUSE)."""
    served = []

    def _fake_run(argv, **kwargs):
        served.append(argv[2])
        return _Proc(out="stopping")

    _cli(monkeypatch, _fake_run, drain_closed=False, listening=True)
    ok, detail = omni.restart(20128, drain_wait_s=0.1)
    assert ok is False
    assert "не отдал порт" in detail
    assert served == ["stop"]          # serve не звали вовсе


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
