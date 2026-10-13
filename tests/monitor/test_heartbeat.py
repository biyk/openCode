import os
import time

from lib.monitor import registry
from lib.monitor.heartbeat import (
    HeartbeatWriter, default_path, heartbeat_age, is_stale, read_heartbeat,
    write_heartbeat,
)
from lib.monitor.registry import ServiceRegistry


def test_write_then_read(tmp_path):
    path = str(tmp_path / "hb.json")
    r = ServiceRegistry()
    r.report("stt", "Слушалка", registry.WORKING)
    write_heartbeat(r, path)
    data = read_heartbeat(path)
    assert data is not None
    assert data["services"]["stt"]["state"] == registry.WORKING


def test_atomic_replace_no_tmp_leftover(tmp_path):
    path = str(tmp_path / "hb.json")
    r = ServiceRegistry()
    r.report("x", "X", registry.IDLE)
    write_heartbeat(r, path)
    write_heartbeat(r, path)
    assert os.path.exists(path)
    assert not os.path.exists(path + ".tmp")


def test_read_missing_returns_none(tmp_path):
    assert read_heartbeat(str(tmp_path / "nope.json")) is None


def test_read_broken_returns_none(tmp_path):
    path = tmp_path / "hb.json"
    path.write_text("{не json", encoding="utf-8")
    assert read_heartbeat(str(path)) is None


def test_stale_when_old(tmp_path):
    r = ServiceRegistry()
    r.report("x", "X", registry.WORKING)
    path = str(tmp_path / "hb.json")
    write_heartbeat(r, path)
    assert is_stale(read_heartbeat(path), stale_s=999) is False
    assert is_stale({"ts": time.time() - 1000}, stale_s=5) is True
    assert is_stale(None) is True


def test_heartbeat_age(tmp_path):
    r = ServiceRegistry()
    r.report("x", "X", registry.WORKING)
    path = str(tmp_path / "hb.json")
    write_heartbeat(r, path)
    assert heartbeat_age(read_heartbeat(path)) is not None
    assert heartbeat_age(None) is None


def test_writer_loop_writes_and_stops(tmp_path):
    path = str(tmp_path / "hb.json")
    r = ServiceRegistry()
    r.report("x", "X", registry.WORKING)
    w = HeartbeatWriter(r, path=path, interval=0.05)
    w.start()
    deadline = time.time() + 2
    while time.time() < deadline and not os.path.exists(path):
        time.sleep(0.05)
    w.stop()
    assert os.path.exists(path)


def test_writer_join_works(tmp_path):
    """`join()` обязан работать: Event в атрибуте `_stop` перекрывал метод
    `Thread._stop()`, и ожидание потока падало с TypeError."""
    path = str(tmp_path / "hb.json")
    w = HeartbeatWriter(ServiceRegistry(), path=path, interval=0.05)
    w.start()
    w.stop()
    w.join(2)
    assert not w.is_alive()


def test_default_path_absolute():
    assert os.path.isabs(default_path())
