import sys


class TranscriptionOutput:
    """Вывод информации в консоль."""

    def __init__(self, use_color: bool = False):
        self.use_color = use_color

    def print_text(self, text: str):
        """Выводит текст в stdout."""
        if text.strip():
            print(text)

    def print_partial(self, text: str):
        """Выводит частичный текст для предпросмотра."""
        if text.strip():
            sys.stdout.write(f"\r{text}")
            sys.stdout.flush()

    def print_progress(self, current: int, total: int, prefix: str = "Загрузка"):
        """Выводит индикатор прогресса."""
        if total > 0:
            percent = (current / total) * 100
            sys.stdout.write(f"\r{prefix}: {percent:.1f}%")
            sys.stdout.flush()
        else:
            sys.stdout.write(f"\r{prefix}...")
            sys.stdout.flush()

    def print_info(self, message: str):
        """Выводит информационное сообщение."""
        print(message)

    def print_error(self, message: str):
        """Выводит сообщение об ошибке в stderr."""
        print(message, file=sys.stderr)

    def print_stopped(self):
        """Выводит сообщение об остановке."""
        print("\nЗапись остановлена.")
