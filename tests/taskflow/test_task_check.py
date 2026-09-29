"""Тесты оценки таблицы задач: запущенные строки и переработка (task_check)."""

from lib.taskflow.task_check import evaluate, find_overtime


def _row(title="Уборка", start=0, uuid="u-1"):
    """Строка real_life_tasks в том виде, как её отдаёт read_all_tasks."""
    return {"task_title": title, "task_time": 10, "start_date": start,
            "task_uuid": uuid}


class TestEvaluateIdle:
    """Ни одной запущенной задачи — idle."""

    def test_all_zeroes_is_idle(self):
        """'' / '0' / 0 / None в start_date — задача не запущена."""
        check = evaluate([_row(start=0), _row(start="0"),
                          _row(start=""), _row(start=None)])
        assert check.idle is True
        assert check.running == []

    def test_started_row_is_not_idle(self):
        """start_date = мс-время — задача в работе."""
        check = evaluate([_row(start=1_700_000_000_000)])
        assert check.idle is False
        assert len(check.running) == 1
        assert check.running[0].title == "Уборка"
        assert check.running[0].uuid == "u-1"

    def test_text_timestamp_counts_as_started(self):
        """JS-клиент пишет mс текстом («1700…») — это тоже запуск."""
        check = evaluate([_row(start="1700000000000")])
        assert [t.title for t in check.running] == ["Уборка"]


class TestRunningRows:
    """В running — все запущенные строки, в том числе несколько."""

    def test_keeps_every_running_row(self):
        check = evaluate([_row(title="Ранняя", start=1_700_000_000_000),
                          _row(title="Вторая", start=1_700_000_060_000),
                          _row(title="Ранняя", start=0)])
        assert [t.title for t in check.running] == ["Ранняя", "Вторая"]

    def test_blank_cells_are_stripped(self):
        """Пустые название/uuid в строке не роняют оценку (берётся '')."""
        check = evaluate([_row(title="  ", start=1_700_000_000_000, uuid=None)])
        assert check.running[0].title == ""
        assert check.running[0].uuid == ""


class TestOvertime:
    """Переработка: задача идёт дольше task_time × множителя (норма B)."""

    MIN = 60_000                                        # мс в минуте
    START = 1_700_000_000_000

    def _check(self, plan=93, start=None):
        return evaluate([{"task_title": "Обед", "task_time": plan,
                          "start_date": start or self.START,
                          "task_uuid": "u-1"}])

    def test_evaluate_keeps_start_and_plan(self):
        """evaluate кладёт в RunningTask старт (мс) и норму (мин)."""
        task = self._check(plan=93).running[0]
        assert task.start_ms == self.START
        assert task.task_time == 93

    def test_over_multiplier_is_overtime(self):
        """169 мин при норме 93 (×1,2 = 111,6) — переработка."""
        now = self.START + 169 * self.MIN
        over = find_overtime(self._check(plan=93), now, multiplier=1.2)
        assert len(over) == 1
        assert over[0].title == "Обед"
        assert over[0].plan == 93
        assert over[0].elapsed == 169

    def test_within_multiplier_is_not_overtime(self):
        """Ровно норма ×1,2 ещё не переработка (строже, чем порог)."""
        now = self.START + 100 * self.MIN
        assert find_overtime(self._check(plan=93), now, multiplier=1.2) == []

    def test_zero_plan_is_skipped(self):
        """Норма ≤ 0 (план не задан) — сравнивать не с чем, не звеним."""
        now = self.START + 999 * self.MIN
        assert find_overtime(self._check(plan=0), now, multiplier=1.2) == []

    def test_idle_check_has_no_overtime(self):
        """Ничего не запущено — переработки нет."""
        assert find_overtime(self._check(start=0), self.START) == []
