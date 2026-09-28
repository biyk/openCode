"""Тесты оценки таблицы задач: запущенные строки (task_check)."""

from lib.taskflow.task_check import evaluate


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
