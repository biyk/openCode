# TOOLTIP: Тесты взгляда на процесс OmniRouter: pid-файл, живость, соединения netstat
"""Тесты взгляда на процесс OmniRouter снаружи (`lib/monitor/omni_proc.py`).

Здесь решается, что смотритель имеет право убивать, а что нет, поэтому данные
подменяются на уровне файлов и `subprocess.run`: живого процесса в тесте быть не
должно.
"""
import os

from lib.monitor import omni_proc
from lib.runtime import win_com as w


class _Out:
    def __init__(self, stdout=""):
        self.stdout = stdout


NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:20128          127.0.0.1:55123        ESTABLISHED       21932
  TCP    127.0.0.1:55123        127.0.0.1:20128        ESTABLISHED       9999
  TCP    0.0.0.0:20128          0.0.0.0:0              LISTENING         21932
  TCP    [::]:20128             [::]:0                 LISTENING         21932
  TCP    127.0.0.1:8765         127.0.0.1:55140        ESTABLISHED       7777
"""


def _data(tmp_path, monkeypatch):
    monkeypatch.setattr(omni_proc, "DATA_DIR", tmp_path)
    return tmp_path


def test_pid_file_is_under_omniroute_home():
    assert omni_proc.pid_file().parts[-2:] == ("server", ".pid")


def test_file_pid_reads_last_line(tmp_path, monkeypatch):
    pid = _data(tmp_path, monkeypatch) / "server"
    pid.mkdir()
    (pid / ".pid").write_text("мусор\n4242\n", encoding="utf-8")
    assert omni_proc.file_pid() == 4242


def test_file_pid_none_without_file(tmp_path, monkeypatch):
    _data(tmp_path, monkeypatch)
    assert omni_proc.file_pid() is None


def test_file_pid_none_on_garbage(tmp_path, monkeypatch):
    pid = _data(tmp_path, monkeypatch) / "server"
    pid.mkdir()
    (pid / ".pid").write_text("", encoding="utf-8")
    assert omni_proc.file_pid() is None


def test_pid_alive_true_for_our_own_process():
    assert omni_proc.pid_alive(os.getpid()) is True


def test_pid_alive_false_for_missing_process():
    assert omni_proc.pid_alive(0x7FFFFFE0) is False


def test_pid_alive_none_without_kernel32(monkeypatch):
    monkeypatch.setattr(w, "WINDLL", None)
    assert omni_proc.pid_alive(os.getpid()) is None


def test_pid_alive_none_for_zero_pid():
    assert omni_proc.pid_alive(0) is None


def test_server_running_false_without_pid_file(tmp_path, monkeypatch):
    """Нет файла — нет и «висяка»: поднимать нужно, а не дренажить."""
    _data(tmp_path, monkeypatch)
    assert omni_proc.server_running() is False


def test_server_running_follows_the_process(tmp_path, monkeypatch):
    pid = _data(tmp_path, monkeypatch) / "server"
    pid.mkdir()
    (pid / ".pid").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(omni_proc, "pid_alive", lambda p: True)
    assert omni_proc.server_running() is True
    monkeypatch.setattr(omni_proc, "pid_alive", lambda p: None)
    assert omni_proc.server_running() is None    # не проверили — не решаем


def test_active_connections_counts_only_server_side_established(monkeypatch):
    """Соединение считается со стороны сервера (локальный порт = порт шлюза).

    Рядом стоящая строка клиента на тот же порт и LISTENING-строки считаться
    не должны: иначе «занят» показывал бы сам себя (нашу же пробу) или нуль
    слушающих сокетов.
    """
    seen = []

    def _fake_run(argv, **kwargs):
        seen.append(argv)
        return _Out(NETSTAT)

    monkeypatch.setattr(omni_proc.subprocess, "run", _fake_run)
    assert omni_proc.active_connections(20128) == 1
    assert seen[0] == ["netstat", "-ano", "-p", "tcp"]


def test_active_connections_zero_when_only_listening(monkeypatch):
    only = ("  TCP    0.0.0.0:20128      0.0.0.0:0              LISTENING   "
            "  21932\n")
    monkeypatch.setattr(omni_proc.subprocess, "run",
                        lambda argv, **kw: _Out(only))
    assert omni_proc.active_connections(20128) == 0


def test_active_connections_none_is_not_zero(monkeypatch):
    """netstat упал — нельзя вернуть 0: смотритель прочитает «простаивает»."""
    def _boom(argv, **kwargs):
        raise OSError("netstat не найден")

    monkeypatch.setattr(omni_proc.subprocess, "run", _boom)
    assert omni_proc.active_connections(20128) is None


def test_active_connections_handles_ipv6_endpoint(monkeypatch):
    row = "  TCP    [::]:20128           [::1]:55123            ESTABLISHED  1\n"
    monkeypatch.setattr(omni_proc.subprocess, "run",
                        lambda argv, **kw: _Out(row))
    assert omni_proc.active_connections(20128) == 1
