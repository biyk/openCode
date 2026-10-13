import threading

from lib.monitor import registry
from lib.monitor.registry import ServiceRegistry


def test_report_and_snapshot():
    r = ServiceRegistry()
    r.report("a", "А", registry.WORKING)
    snap = r.snapshot()
    assert snap["a"]["state"] == registry.WORKING
    assert snap["a"]["name"] == "А"


def test_report_overwrites_same_id():
    r = ServiceRegistry()
    r.report("a", "А", registry.WORKING)
    r.report("a", "А", registry.IDLE, "ждёт")
    assert r.snapshot()["a"]["state"] == registry.IDLE
    assert r.snapshot()["a"]["detail"] == "ждёт"


def test_snapshot_is_copy():
    r = ServiceRegistry()
    r.report("a", "А", registry.WORKING)
    snap = r.snapshot()
    snap["a"]["state"] = "мусор"
    assert r.snapshot()["a"]["state"] == registry.WORKING


def test_threadsafe_many_reports():
    r = ServiceRegistry()

    def hammer(i):
        for _ in range(200):
            r.report(f"s{i}", "S", registry.WORKING)

    ts = [threading.Thread(target=hammer, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(r.snapshot()) == 8


def test_red_states_membership():
    assert registry.DISABLED in registry.RED_STATES
    assert registry.WORKING not in registry.RED_STATES
