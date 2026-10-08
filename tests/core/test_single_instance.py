# TOOLTIP: Тесты single_instance: bind/second-fail/реакквест + wiring в main.py
"""Тесты `lib/core/single_instance.py` и его wiring'а в `main.py`.

Что ловим:
- `acquire()` возвращает живой сокет при свободном порту;
- повторный `acquire()` на том же порту бросает `AlreadyRunning`
  (ровно то, что нужно: второй экземпляр обязан не поднимать потоки);
- текст исключения содержит подсказку `netstat` и `taskkill` — юзер
  сможет убить зависший процесс, не читая исходники guard'а;
- после `sock.close()` порт освобождается, reacquire работает (иначе
  обычная смерть процесса оставляла бы «залипший» lock);
- `main.py` вызывает `acquire()` ДО `start_version_checker`,
  `TranscriptionWorker`, `CronScheduler`, `start_telegram`,
  `start_task_monitor` (иначе второй экземпляр всё равно успеет
  поднять Vosk/Telegram/TTS-потоки, а мы этого боимся).

Порты для тестов берём ephemeral (`bind(0)`): не трогаем `LOCK_PORT`
реального приложения и не конфликтует с соседними тестами.
"""

import socket
from pathlib import Path

import pytest

from lib.core.single_instance import (
    AlreadyRunning,
    _hint,
    acquire,
)


def _free_port() -> int:
    """Попросить у ядра свободный ephemeral-порт, тотчас освободив его."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestAcquire:
    """Прямое поведение блокировки."""

    def test_returns_live_socket(self):
        port = _free_port()
        sock = acquire(port)
        try:
            assert sock.fileno() != -1        # fd жив, порт занят
            assert sock.getsockname()[1] == port
        finally:
            sock.close()

    def test_second_acquire_raises(self):
        port = _free_port()
        sock = acquire(port)
        try:
            with pytest.raises(AlreadyRunning):
                acquire(port)
        finally:
            sock.close()

    def test_error_message_hints_netstat_and_taskkill(self):
        port = _free_port()
        sock = acquire(port)
        try:
            with pytest.raises(AlreadyRunning) as exc:
                acquire(port)
            text = str(exc.value)
            assert str(port) in text
            assert "netstat" in text
            assert "taskkill" in text
        finally:
            sock.close()

    def test_reacquire_after_close(self):
        # Смерть держателя освобождает порт: guard не должен «залипать».
        port = _free_port()
        sock1 = acquire(port)
        sock1.close()
        sock2 = acquire(port)
        try:
            assert sock2.fileno() != -1
        finally:
            sock2.close()


class TestHint:
    """Подсказка в AlreadyRunning — человекочитаемая, с конкретикой."""

    def test_hint_mentions_port_and_pid_steps(self):
        text = _hint("127.0.0.1", 51777, OSError("nope"))
        assert "127.0.0.1" in text
        assert "51777" in text
        assert "netstat -ano | findstr :51777" in text
        assert "taskkill /F /PID" in text
        assert "nope" in text        # исходная ошибка тоже приплетена


class TestMainWiring:
    """main.py обязан вызывать acquire() до подъёма любых daemon-потоков."""

    _TARGETS = (
        "start_version_checker(",
        "TranscriptionWorker(",
        "CronScheduler(",
        "start_telegram(",
        "start_task_monitor(",
        "worker.run",       # target=worker.run поднимает Vosk-цикл
    )

    def _main_src(self) -> str:
        return (Path(__file__).resolve().parents[2] / "main.py").read_text(
            encoding="utf-8")

    def test_main_imports_single_instance(self):
        assert "single_instance" in self._main_src()

    def test_acquire_called_before_threads(self):
        src = self._main_src()
        idx = src.find("acquire()")
        assert idx > 0, "main.py не вызывает acquire() — guard не работает"
        for late in self._TARGETS:
            pos = src.find(late)
            assert pos > idx, (
                f"main.py: {late!r} идёт ДО acquire() — "
                f"второй экземпляр успеет поднять потоки")

    def test_failure_path_exits(self):
        """AlreadyRunning обязан ронять процесс, а не глотаться."""
        src = self._main_src()
        assert "AlreadyRunning" in src
        # либо sys.exit(1)/os._exit(1) в except, либо raise — и то и другое
        # заканчивает main(); проверяем, что хотя бы один явный выход есть
        import re
        assert re.search(
            r"except AlreadyRunning( as \w+)?:[\s\S]{0,200}?"
            r"(sys\.exit|os\._exit|raise)",
            src), ("main.py ловит AlreadyRunning, но не выходит — "
                   "второй процесс продолжит работать параллельно")
