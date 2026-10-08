# TOOLTIP: Один экземпляр main.py: bind loopback-порта; второй запуск выходит с подсказкой PID
"""Один запущенный экземпляр: TCP-bind на loopback как блокировка.

Причина: без guard'а второй `python main.py` (F5 в IDE, автоперезапуск
после version_gate, ручной старт в новой консоли) параллельно открывает
тот же микрофон вторым Vosk-воркером, вторым Telegram-потоком (Bot API
отвечает `409 Conflict` на getUpdates) и вторым TTS-плеером. Команды
распознаются дважды, озвучка играет дважды — пользователь слышит
«дубли сообщений». Прямое доказательство из логов: одинаковые
строки в `202610080848.log` и `202610080926.log` (та же `[TEXT]`
фраза в те же секунды `[09:30:44]`) + `409 Client Error` в логе.

Механизм: `bind(127.0.0.1, VOICE_SINGLE_INSTANCE_PORT)` + `listen(1)`.
Порт занят → второй экземпляр выходит ДО запуска потоков. Сокет держим
в main() до конца: процесс умирает (обычный выход, Ctrl+C, os._exit,
kill) — ядро ОС снимает bind автоматически, отдельного «unlock» нет.
"""

import os
import socket
from typing import Optional

# Порт-заглушка: нестандартный, high-range, loopback. Переопределяется
# переменной окружения — на случай, если 51777 на хосте чем-то занят.
LOCK_PORT = int(os.environ.get("VOICE_SINGLE_INSTANCE_PORT", "51777"))
LOCK_HOST = "127.0.0.1"


class AlreadyRunning(RuntimeError):
    """Второй экземпляр: lock-порт занят предыдущим процессом."""


def acquire(port: Optional[int] = None,
            host: str = LOCK_HOST) -> socket.socket:
    """Занять lock-порт; вернуть listening-сокет (держать живым до конца main).

    Сокет возвращаем наружу, а не прячем в module-level: GC закроет fd
    раньше времени, если ссылка потеряется. Неудача — AlreadyRunning с
    подсказкой, как найти и убить предыдущий процесс (netstat → PID →
    taskkill). Специально НЕ ставим SO_REUSEADDR: он бы позволил второму
    экземпляру пере-биндить тот же порт, а это ровно то, чего боимся.
    """
    use_port = LOCK_PORT if port is None else port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, use_port))
        sock.listen(1)
    except OSError as exc:
        sock.close()
        raise AlreadyRunning(_hint(host, use_port, exc)) from exc
    return sock


def _hint(host: str, port: int, exc: OSError) -> str:
    """Текст подсказки: как найти держателя порта и закрыть его.

    Windows-центрично (проект Windows-only), но netstat есть и в Linux;
    `taskkill` заменим на `kill <PID>`. Исходную ошибку приплетаем в
    конец — без неё при нетипичном сбое (например, EADDRNOTAVAIL из-за
    другой причины) пользователь останется гадать.
    """
    return (
        f"Приложение уже запущено: {host}:{port} занят. "
        f"Найди процесс: `netstat -ano | findstr :{port}` — "
        f"последняя колонка и есть PID. Закрой его (Ctrl+C в его консоли "
        f"или `taskkill /F /PID <PID>`) и повтори запуск. "
        f"Исходная ошибка: {exc}"
    )
