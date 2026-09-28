"""Тесты заполнения дыр развлечениями (lib/taskflow/fun_fill)."""

import json
from datetime import datetime

import pytest

from lib.taskflow import fun_fill
from lib.taskflow.fun_fill import fill, make_fun_fill
from lib.taskflow.fun_holes import FUN_MARKER

TZ = datetime.now().astimezone().tzinfo
NOW = datetime(2026, 9, 28, 14, 0, tzinfo=TZ)
REWARD = {"title": "1час развлечений ", "reward_id": "a99c1560", "cost": 60}


def _at(hour, minute=0, second=0):
    return datetime(2026, 9, 28, hour, minute, second, tzinfo=TZ)


def _ev(start, end, color="", summary="Задача", desc=""):
    """Событие вида list_events_between (ISO-строки с часовым поясом)."""
    return {"id": f"{summary}-{start}", "summary": summary,
            "start": _at(*start).isoformat(), "end": _at(*end).isoformat(),
            "description": desc, "colorId": color}


def _events():
    """Сон до 09:00, синие 09:00–09:30 и 10:00–10:30 → дыра 30 мин."""
    return [_ev((6, 0), (9, 0), color="7", summary="СОН"),
            _ev((9, 0), (9, 30), color="7"),
            _ev((10, 0), (10, 30), color="7"),
            _ev((0, 30), (0, 45), color="9", summary="тест для цвета")]


def _gcal(mocker, events=None, created="evt-1"):
    gcal = mocker.MagicMock()
    gcal.list_events_between.return_value = (events if events is not None
                                             else _events())
    gcal.create_task_event.return_value = created
    return gcal


def _sheet(mocker, reward=REWARD):
    sheet = mocker.MagicMock()
    sheet.find_reward.return_value = reward
    return sheet


@pytest.fixture(autouse=True)
def audit_file(tmp_path, monkeypatch):
    """Аудит — во временный файл, а не в боевой logs/."""
    path = tmp_path / "fun_holes.log"
    monkeypatch.setattr(fun_fill, "AUDIT_PATH", path)
    return path


def _entries(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestFill:
    """Один проход: событие нужного цвета + списание по минутам."""

    def test_event_uses_rest_title_marker_and_color(self, mocker):
        gcal, sheet = _gcal(mocker), _sheet(mocker)
        assert fill(gcal, sheet, now=NOW) == 1
        args, kwargs = gcal.create_task_event.call_args
        # В календаре — короткое «Отдых», а не имя награды из таблицы
        assert args[0] == fun_fill.FUN_EVENT_TITLE
        assert args[1] == FUN_MARKER
        assert args[2] == _at(9, 30) and args[3] == _at(10, 0)
        assert kwargs["color_id"] == "9"

    def test_journal_keeps_reward_title(self, mocker):
        """Покупателем остаётся награда из real_life_rewards, а не «Отдых»."""
        gcal, sheet = _gcal(mocker), _sheet(mocker)
        fill(gcal, sheet, now=NOW)
        assert sheet.spend.call_args.args[0] == REWARD
        assert gcal.create_task_event.call_args.args[0] != REWARD["title"]

    def test_reward_is_looked_up_by_tuning_title(self, mocker):
        sheet = _sheet(mocker)
        fill(_gcal(mocker), sheet, now=NOW)
        assert sheet.find_reward.call_args.args[0] == fun_fill.FUN_REWARD_TITLE

    def test_money_equals_rounded_minutes(self, mocker):
        """Дыра 26.4 мин → списано 26 (1 минута = 1 hero_money)."""
        events = [_ev((6, 0), (9, 0), color="7", summary="СОН"),
                  _ev((9, 0), (9, 30), color="7"),
                  _ev((9, 56, 24), (10, 30), color="7")]
        sheet = _sheet(mocker)
        fill(_gcal(mocker, events), sheet, now=NOW)
        assert sheet.spend.call_args.args[1] == 26

    def test_every_hole_gets_its_own_row(self, mocker):
        """Одна строка журнала на каждое списание: дыра → spend один раз."""
        gcal, sheet = _gcal(mocker), _sheet(mocker)
        assert fill(gcal, sheet, now=NOW) == 1
        sheet.spend.assert_called_once_with(REWARD, 30, NOW)

    def test_dry_run_writes_nothing(self, mocker):
        gcal, sheet = _gcal(mocker), _sheet(mocker)
        assert fill(gcal, sheet, now=NOW, dry=True) == 1
        gcal.create_task_event.assert_not_called()
        sheet.spend.assert_not_called()

    def test_missing_reward_skips_calendar_too(self, mocker):
        """Нет награды в real_life_rewards — ни событий, ни списаний."""
        gcal, sheet = _gcal(mocker), _sheet(mocker, reward=None)
        assert fill(gcal, sheet, now=NOW) == 0
        gcal.create_task_event.assert_not_called()

    def test_failed_event_does_not_spend(self, mocker):
        gcal, sheet = _gcal(mocker, created=""), _sheet(mocker)
        assert fill(gcal, sheet, now=NOW) == 0
        sheet.spend.assert_not_called()

    def test_spend_failure_is_only_logged(self, mocker):
        """Событие создано, таблица не записалась — исключения наружу нет."""
        gcal, sheet = _gcal(mocker), _sheet(mocker)
        sheet.spend.side_effect = OSError("sheets 500")
        assert fill(gcal, sheet, now=NOW) == 0

    def test_no_holes_is_quiet_zero(self, mocker):
        events = [_ev((6, 0), (9, 0), color="7", summary="СОН")]
        gcal, sheet = _gcal(mocker, events), _sheet(mocker)
        assert fill(gcal, sheet, now=NOW) == 0
        sheet.find_reward.assert_not_called()


class TestAudit:
    """Раз озвучки нет, каждое действие обязано остаться в logs/fun_holes.log."""

    def test_fill_is_audited_with_money_and_ids(self, mocker, audit_file):
        fill(_gcal(mocker), _sheet(mocker), now=NOW)
        fill_entry, run_entry = _entries(audit_file)
        assert fill_entry["action"] == "fill"
        assert fill_entry["hole_start"] == _at(9, 30).isoformat()
        assert fill_entry["hole_end"] == _at(10, 0).isoformat()
        assert fill_entry["gold_spent"] == 30
        assert fill_entry["event_id"] == "evt-1"
        assert fill_entry["event_title"] == fun_fill.FUN_EVENT_TITLE
        assert fill_entry["reward_title"] == REWARD["title"]
        assert fill_entry["ok"] is True
        assert run_entry["action"] == "run"
        assert run_entry["holes_found"] == run_entry["filled"] == 1
        assert run_entry["gold_spent_total"] == 30

    def test_failed_spend_is_audited_without_claim(self, mocker, audit_file):
        sheet = _sheet(mocker)
        sheet.spend.side_effect = OSError("sheets 500")
        fill(_gcal(mocker), sheet, now=NOW)
        entry = _entries(audit_file)[0]
        assert entry["ok"] is False
        assert entry["event_id"] == "evt-1"      # событие создано
        assert entry["claim_item_id"] is None    # а денег не списано
        assert "sheets 500" in entry["error"]

    def test_dry_run_writes_no_audit(self, mocker, audit_file):
        fill(_gcal(mocker), _sheet(mocker), now=NOW, dry=True)
        assert _entries(audit_file) == []


class TestHookForMonitor:
    """Замыкание для task_monitor: клиенты один раз, сбои — в лог."""

    def test_errors_never_reach_the_loop(self, mocker):
        mocker.patch.object(fun_fill, "GoogleCalendar",
                            side_effect=RuntimeError("нет токена"))
        run = make_fun_fill(mocker.MagicMock())
        run()   # исключения наружу — цикл монитора живой

    def test_clients_are_built_once(self, mocker):
        gcal_cls = mocker.patch.object(fun_fill, "GoogleCalendar")
        mocker.patch.object(fun_fill, "RewardsSheet")
        run = make_fun_fill(mocker.MagicMock())
        run()
        run()
        assert gcal_cls.call_count == 1
