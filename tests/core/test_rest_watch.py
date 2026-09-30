"""тесты lib/core/rest_watch.py — фоновая (вне цикла монитора) проверка окна."""

from lib.core.rest_watch import RestWatch
from lib.rest_check import RestAnswer

REST = RestAnswer("да", 80, "это игра", True)
NOT_REST = RestAnswer("нет", 90, "работа", False)


class FakeThread:
    """Заглушка threading.Thread: копит цели, не запуская реальные потоки."""

    def __init__(self, target=None, **_kw):
        self._target = target

    def start(self):
        FakeThread.launches.append(self._target)


def _patch_thread(mocker):
    FakeThread.launches = []
    mocker.patch("lib.core.rest_watch.threading.Thread", FakeThread)
    return FakeThread.launches


def _watch(mocker, res, title="Игра"):
    out = mocker.MagicMock()
    return RestWatch(lambda: title, lambda _t: res, out), out


class TestRestWatchRun:
    def test_rest_is_announced(self, mocker):
        w, out = _watch(mocker, REST)
        w._run()
        msg = out.print_info.call_args.args[0]
        assert "Игра" in msg and "80" in msg

    def test_not_rest_is_silent(self, mocker):
        w, out = _watch(mocker, NOT_REST)
        w._run()
        out.print_info.assert_not_called()

    def test_primitive_error_is_swallowed(self, mocker):
        def boom(_t):
            raise OSError("network")
        out = mocker.MagicMock()
        RestWatch(lambda: "X", boom, out)._run()   # не должен бросить
        out.print_info.assert_not_called()

    def test_run_clears_running_flag(self, mocker):
        w, _ = _watch(mocker, NOT_REST)
        w._running = True
        w._run()
        assert w._running is False


class TestRestWatchDispatch:
    def test_disabled_without_primitives(self, mocker):
        launches = _patch_thread(mocker)
        w = RestWatch(None, None, mocker.MagicMock())
        assert w.enabled is False
        w.check_async()
        assert launches == []

    def test_launches_one_thread_and_guards_reentry(self, mocker):
        launches = _patch_thread(mocker)
        w, _ = _watch(mocker, REST)
        w.check_async()
        assert len(launches) == 1
        w.check_async()                # предыдущая «в работе» — новую не плодим
        assert len(launches) == 1
        launches[0]()                  # исполняем тело — оно сбросит флаг
        w.check_async()                # теперь можно снова
        assert len(launches) == 2

    def test_check_async_does_not_block(self, mocker):
        """check_async возвращается сразу, даже когда модель ещё не ответила."""
        _patch_thread(mocker)
        w, out = _watch(mocker, REST)
        w.check_async()
        out.print_info.assert_not_called()   # печать — в потоке, не в вызвавшем
