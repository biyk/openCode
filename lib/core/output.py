import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


class TranscriptionOutput:
    """Вывод информации в консоль (кратко) и лог-файл (подробно).

    Консоль остаётся краткой: распознанный текст, команды, ошибки.
    Всё, включая отладочные данные, дополнительно пишется в единый
    лог-файл сеанса (`logs/<запуск>.log`), чтобы можно было
    анализировать работу ассистента постфактум.
    """

    def __init__(self, use_color: bool = False, log_file: Optional[str] = None):
        self.use_color = use_color
        self._log_file = log_file or self._default_log_path()

    @staticmethod
    def _default_log_path() -> str:
        """Формирует путь лог-файла по времени запуска (ГГГГММДДЧЧММ.log)."""
        base = Path("logs")
        base.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d%H%M")
        return str(base / f"{timestamp}.log")

    def _log(self, level: str, message: str) -> None:
        """Дописывает сообщение с меткой времени в лог-файл."""
        if not message.strip():
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] [{level}] {message}\n")

    def print_text(self, text: str):
        """Выводит текст в stdout и лог."""
        if text.strip():
            print(text)
            self._log("TEXT", text)

    def print_partial(self, text: str):
        """Выводит частичный текст для предпросмотра."""
        if text.strip():
            sys.stdout.write(f"\r{text}")
            sys.stdout.flush()
            self._log("PARTIAL", text)

    def print_progress(self, current: int, total: int, prefix: str = "Загрузка"):
        """Выводит индикатор прогресса."""
        if total > 0:
            percent = (current / total) * 100
            sys.stdout.write(f"\r{prefix}: {percent:.1f}%")
            sys.stdout.flush()
        else:
            sys.stdout.write(f"\r{prefix}...")
            sys.stdout.flush()
        self._log("PROGRESS", f"{prefix}: {current}/{total}")

    def print_info(self, message: str):
        """Выводит информационное сообщение."""
        print(message)
        self._log("INFO", message)

    def print_error(self, message: str):
        """Выводит сообщение об ошибке в stderr."""
        print(message, file=sys.stderr)
        self._log("ERROR", message)

    def print_debug(self, message: str):
        """Пишет отладочную информацию только в лог-файл."""
        self._log("DEBUG", message)

    def print_stopped(self):
        """Выводит сообщение об остановке."""
        print("\nЗапись остановлена.")
        self._log("STOPPED", "Запись остановлена.")
