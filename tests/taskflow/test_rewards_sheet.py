"""Тесты каталога наград и журнала списаний (lib/taskflow/rewards_sheet)."""

from datetime import datetime

from lib.taskflow.rewards_sheet import (HERO_EPOCH_DAYS, MS_PER_DAY,
                                        RewardsSheet)

TZ = datetime.now().astimezone().tzinfo
NOW = datetime(2026, 9, 28, 14, 0, tzinfo=TZ)
HEADER = ["reward_title", "reward_cost", "reward_id"]
ROWS = [HEADER, ["1час развлечений ", 60, "a99c1560-9bb6"],
        ["1 час VR", 100, "df0ffd03-6ac0"]]


class _Fake(RewardsSheet):
    """Лист без OAuth: _get отдаёт заготовку, append падает в мок сервиса."""

    def __init__(self, mocker, rows=None):
        self._gcal = None
        self._spreadsheet_id = "sid"
        self._service = mocker.MagicMock()
        self._rows = rows if rows is not None else ROWS
        self.spent = []

    def _get(self, rng):
        return self._rows

    def _ensure_service(self):
        return self._service

    def add_hero_money(self, delta):
        self.spent.append(delta)

    def appended_row(self):
        append = _appender(self)
        return append.call_args.kwargs["body"]["values"][0]


def _appender(sheet):
    """Мок-метод values().append() сервиса Sheets."""
    return (sheet._service.spreadsheets.return_value
            .values.return_value.append)


class TestFindReward:
    """Награда ищется по заголовку как в JS: без регистра и лишних пробелов."""

    def test_match_ignores_case_and_extra_spaces(self, mocker):
        sheet = _Fake(mocker)
        found = sheet.find_reward("1ЧАС   развлечений")
        assert found["reward_id"] == "a99c1560-9bb6"
        assert found["title"] == "1час развлечений "   # как в таблице
        assert found["cost"] == 60.0

    def test_absent_reward_returns_none(self, mocker):
        assert _Fake(mocker).find_reward("еда") is None


class TestClaimRow:
    """Строка rewards_history повторяет колонки JS-клиента (A:F)."""

    def test_spend_subtracts_money(self, mocker):
        sheet = _Fake(mocker)
        sheet.spend(sheet.find_reward("1час развлечений"), 30, NOW)
        assert sheet.spent == [-30.0]

    def test_row_columns_in_client_order(self, mocker):
        sheet = _Fake(mocker)
        reward = sheet.find_reward("1час развлечений")
        sheet.append_claim(reward, 30, NOW)
        row = sheet.appended_row()
        assert row[1] == int(NOW.timestamp() * 1000)
        assert row[2] == 30
        assert row[3] == "1час развлечений "
        assert row[4] == "a99c1560-9bb6"
        assert row[5] == row[1] / MS_PER_DAY + HERO_EPOCH_DAYS
        assert len(row[0]) == 36                     # uuid4 покупки

    def test_append_targets_history_sheet(self, mocker):
        sheet = _Fake(mocker)
        sheet.append_claim({"title": "t", "reward_id": "r"}, 5, NOW)
        rng = _appender(sheet).call_args.kwargs["range"]
        assert rng.endswith("rewards_history!A:F")
