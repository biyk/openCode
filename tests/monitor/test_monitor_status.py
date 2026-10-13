"""Тесты слияния статуса для GUI (`lib/monitor/status.py`).

Файл назван test_monitor_status.py, а не test_status.py: в tests/ нет
пакетов (`__init__.py` почти везде), поэтому pytest в режиме prepend грузит
модули по basename — два `test_status.py` (наш и
`tests/runtime/test_status.py`) столкнулись бы при прогоне всего `tests/`
и сломали коллективание.
"""
import inspect
import json
import time

from lib.monitor import heartbeat, registry
from lib.monitor.status import collect
from lib.monitor.tuning import MONITOR_STALE_S


def _write_hb(path, services, ts=None):
    data = {"ts": ts if ts is not None else time.time(), "services": services}
    path.write_text(json.dumps(data), encoding="utf-8")


def test_collect_in_main_services(tmp_path):
    p = tmp_path / "hb.json"
    _write_hb(p, {"stt": {"name": "Слушалка", "state": registry.WORKING,
                          "detail": ""}})
    res = collect(heartbeat_path=str(p), probe=False)
    ids = {s["id"]: s for s in res["services"]}
    assert ids["stt"]["state"] == registry.WORKING
    assert res["stale"] is False


def test_collect_stale_marks_error(tmp_path):
    p = tmp_path / "hb.json"
    _write_hb(p, {"stt": {"name": "Слушалка", "state": registry.WORKING}},
              ts=1.0)
    res = collect(heartbeat_path=str(p), probe=False, stale_s=5)
    assert res["stale"] is True
    assert all(s["state"] == registry.ERROR for s in res["services"])


def test_collect_no_file_marks_main_never(tmp_path):
    p = tmp_path / "missing.json"
    res = collect(heartbeat_path=str(p), probe=False)
    assert res["services"][0]["id"] == "main"
    assert res["services"][0]["state"] == registry.NEVER


def test_collect_disabled_state_passthrough(tmp_path):
    p = tmp_path / "hb.json"
    _write_hb(p, {"telegram": {"name": "TG", "state": registry.DISABLED,
                               "detail": "выкл"}})
    res = collect(heartbeat_path=str(p), probe=False)
    assert res["services"][0]["state"] == registry.DISABLED


def test_collect_age_s_reported(tmp_path):
    p = tmp_path / "hb.json"
    _write_hb(p, {"x": {"name": "X", "state": registry.IDLE}})
    res = collect(heartbeat_path=str(p), probe=False)
    assert isinstance(res["age_s"], float)


def test_stale_default_follows_monitor_tuning():
    """Просрочка по умолчанию = MONITOR_STALE_S (дефолт лежит в
    lib/monitor/tuning.py): GUI красит всё по настройке, а не на глаз,
    и status.py с heartbeat.py берут один и тот же порог."""
    got = inspect.signature(collect).parameters["stale_s"].default
    assert got == MONITOR_STALE_S
    hb = inspect.signature(heartbeat.is_stale).parameters["stale_s"].default
    assert hb == MONITOR_STALE_S
