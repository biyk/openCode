"""Тесты lib/core/timing.py: засечки длительности шагов команды.

Повод: между «[Command] Распознана команда: taskdone» и первым выводом
проходило ~15 c тишины. Их съедали ~12 последовательных запросов к Google,
а печатать было нечего — процесс молчал до самого конца.
"""
from pathlib import Path

import pytest

from lib.core import timing

REPO_ROOT = Path(__file__).resolve().parents[2]

# Файлы, где каждый Google round trip обёрнут в timing.execute/measure.
TRACED = [
    "lib/google/google_calendar_events.py",
    "lib/google/google_calendar_mutate.py",
    "lib/google/google_tasks.py",
    "lib/google/shopping_sheet.py",
    "lib/taskflow/real_life_sheet.py",
    "lib/taskflow/rewards_sheet.py",
]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Журнал — во временный каталог; трассировка и env — выключены."""
    monkeypatch.setattr(timing, "LOG_FILE", str(tmp_path / "timing.log"))
    monkeypatch.delenv(timing.ENV_SWITCH, raising=False)
    timing.disable()
    yield
    timing.disable()


def _log_text():
    with open(timing.LOG_FILE, encoding="utf-8") as f:
        return f.read()


class TestReport:
    """report() — грубая засечка: она печатается всегда."""

    def test_prints_without_detail(self, capsys):
        timing.report("команда taskdone", 15.0)
        assert "[Timing] команда taskdone за 15.0 с" in capsys.readouterr().out

    def test_appends_to_log(self):
        timing.report("команда taskdone", 15.0)
        assert "команда taskdone за 15.0 с" in _log_text()

    def test_broken_log_does_not_break_step(self, monkeypatch, tmp_path,
                                            capsys):
        """Сбой журнала (путь — каталог) не должен валить команду."""
        monkeypatch.setattr(timing, "LOG_FILE", str(tmp_path))
        timing.report("команда tts", 0.5)
        assert "команда tts за 0.5 с" in capsys.readouterr().out


class TestTick:
    """tick() — подробная трассировка, только когда она включена."""

    def test_silent_when_disabled(self, capsys):
        timing.tick("gcal get", 0.6)
        assert capsys.readouterr().out == ""

    def test_prints_step_and_total_when_enabled(self, capsys):
        timing.enable()
        timing.tick("gcal get", 0.61)
        out = capsys.readouterr().out
        assert "gcal get: 0.61 с" in out
        assert "всего" in out

    def test_env_off_wins(self, monkeypatch):
        """VOICE_TIMING=off — детальность не включается даже из CLI."""
        monkeypatch.setenv(timing.ENV_SWITCH, "off")
        timing.enable()
        assert timing.enabled() is False

    def test_env_one_enables_lazily(self, monkeypatch):
        """Проверка из чужого кода: переменная окружения включает сама."""
        monkeypatch.setenv(timing.ENV_SWITCH, "1")
        assert timing.enabled() is True


class TestExecute:
    """execute() — обёртка round trip: результат и судьба запроса."""

    def test_returns_response(self):
        class Req:
            def execute(self):
                return {"items": [1]}

        assert timing.execute(Req(), "gcal list") == {"items": [1]}

    def test_ticks_when_enabled(self, capsys):
        class Req:
            def execute(self):
                return {}

        timing.enable()
        timing.execute(Req(), "sheets get")
        assert "sheets get:" in capsys.readouterr().out

    def test_silent_and_passes_through_when_disabled(self, capsys):
        class Req:
            def execute(self):
                return {}

        assert timing.execute(Req(), "sheets get") == {}
        assert capsys.readouterr().out == ""

    def test_failure_is_traced_and_raised(self, capsys):
        class Req:
            def execute(self):
                raise ValueError("boom")

        timing.enable()
        with pytest.raises(ValueError):
            timing.execute(Req(), "gcal get")
        assert "gcal get — сбой ValueError" in capsys.readouterr().out


class TestMeasure:
    """measure() — засечка произвольного шага (сборка клиента, озвучка)."""

    def test_passes_args_and_kwargs(self):
        assert timing.measure("шаг", lambda a, b=0: a + b, 2, b=3) == 5

    def test_ticks_when_enabled(self, capsys):
        timing.enable()
        timing.measure("озвучка", lambda: None)
        assert "озвучка:" in capsys.readouterr().out


class TestGoogleCallsTraced:
    """Ни одного голого .execute(): каждый round trip с меткой."""

    @pytest.mark.parametrize("relative", TRACED)
    def test_no_bare_execute(self, relative):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert ".execute()" not in source, (
            f"{relative}: запрос без засечки — снова молчаливая пауза; "
            "нужен timing.execute(request, label)")
