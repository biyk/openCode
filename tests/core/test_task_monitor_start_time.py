"""Регресс: старт задачи из TaskMonitor обязан брать СВЕЖЕЕ время.

Баг из логов (02–03.10): «Почистить зубы утром» записало 630 минут вместо
~5. Причина — TaskStartHandler фиксирует now в __init__ (он и нужен таким,
чтобы «сегодня» считалось от одной метки), а TaskMonitor кэшировал ОДИН
handler на весь процесс. Первый ответ после рестарта конструировал handler
(например, в 20:56), и каждая следующая задача в том же процессе получала
этот застывший start_date → утром «зубы» стартанули с вчерашних 20:56.

Фикс: _task_handler() в продакшене (handler=None) строит новый TaskStartHandler
на каждый вызов; внедрённый тестовый handler (truthy) переиспользуется, чтобы
существующие тесты не сломались.
"""

from datetime import datetime, timezone

from lib.core import task_monitor as tm_module
from lib.core.task_monitor import TaskMonitor


def _clock(times):
    """Часы, которые каждый вызов отдают следующую фиксированную метку."""
    seq = list(times)
    return lambda: seq.pop(0)


class _FakeHandler:
    """Копирует суть TaskStartHandler: now замораживается в __init__ и именно
    из него start_task считает new_start (то, что пишется в колонку G)."""

    instances = []      # все построенные за тест handler'ы
    written = []        # new_start каждой запущенной задачи, по порядку

    def __init__(self, now_fn):
        self.now = now_fn()
        _FakeHandler.instances.append(self)

    def find_task_event(self, phrase):
        return {"summary": phrase}

    def start_task(self, title):
        new_start = int(self.now.timestamp() * 1000)
        _FakeHandler.written.append(new_start)
        return {"ok": True, "title": title, "uuid": "u", "row": 15,
                "new_start": new_start}

    @classmethod
    def reset(cls):
        cls.instances = []
        cls.written = []


def _monitor(mocker, now_fn):
    """Монитор в продакшен-конфигурации: handler=None → строит TaskStartHandler."""
    _FakeHandler.reset()
    mocker.patch.object(tm_module, "TaskStartHandler",
                        lambda: _FakeHandler(now_fn))
    monitor = TaskMonitor(ask=mocker.MagicMock(), say=mocker.MagicMock(),
                          output=mocker.MagicMock(), core=lambda t: t,
                          sheet=mocker.MagicMock(), handler=None)
    return monitor


def _ts(day, hour, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second, tzinfo=timezone.utc)


class TestFreshStartPerAnswer:
    """Каждый ответ «чем занимаешься?» стартует по текущему времени."""

    def test_second_answer_stamps_its_own_time(self, mocker):
        """Две задачи в одном процессе: вторая пишется по СВОЕМУ времени.

        На старом (багом) коде — обе получили бы метку первой, т.к. handler
        кэшировался с замороженным now.
        """
        t1 = _ts(2, 20, 56, 47)     # первый ответ вечером — старт «Глобальных»
        t2 = _ts(3, 7, 21, 49)      # следующий ответ утром — старт «зубов»
        monitor = _monitor(mocker, _clock([t1, t1, t2, t2]))
        monitor._on_idle_answer("глобальные задачи")
        monitor._on_idle_answer("почистить зубы утром")
        assert _FakeHandler.written == [
            int(t1.timestamp() * 1000), int(t2.timestamp() * 1000)]
        # 630 минут было бы, если бы «зубы» унаследовали t1:
        inherited = (t2 - t1).total_seconds() / 60
        assert abs(inherited - 630) < 5, "сценарий должен ловить ~630 мин"

    def test_handler_not_cached_in_production(self, mocker):
        """Продакшен (handler=None): _task_handler не пишет в self._handler."""
        monitor = _monitor(mocker, _clock([_ts(2, 9), _ts(2, 10)]))
        first = monitor._task_handler()
        second = monitor._task_handler()
        assert monitor._handler is None, "handler нельзя кэшировать"
        assert first is not second, "нужен новый handler на каждый вызов"


class TestInjectedHandlerReused:
    """Тестовый/внедрённый handler (truthy) переиспользуется — как раньше."""

    def test_same_instance_returned(self, mocker):
        injected = mocker.MagicMock()
        monitor = TaskMonitor(ask=mocker.MagicMock(), say=mocker.MagicMock(),
                              output=mocker.MagicMock(), core=lambda t: t,
                              sheet=mocker.MagicMock(), handler=injected)
        assert monitor._task_handler() is injected
        assert monitor._task_handler() is injected
