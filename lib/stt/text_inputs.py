"""Ручной текстовый ввод команд в консоль (альтернатива голосу)."""
import sys
from typing import Callable, Optional

# Триггер, автоматически дописываемый к напечатанной команде: ручной ввод не
# требует кодового слова — строка считается сразу «с ключом» (§10).
MANUAL_TRIGGER = "пожалуйста"


def submit_manual_text(worker, text: str) -> None:
    """Печатный аналог строки STT: дописывает триггер и гонит в тот же путь.

    Ручной ввод не требует кодового слова — если в строке нет триггера,
    в конец добавляется MANUAL_TRIGGER, и команда сопоставляется без изменений.
    """
    from lib.stt.transcription_worker import _fix_encoding
    text = _fix_encoding(text).strip()
    if not text:
        return
    if not worker._matcher.has_trigger(text):
        text = f"{text} {MANUAL_TRIGGER}"
    worker._logger.log_command(text)
    worker._accumulated.append(text)
    worker._orchestrator.process_text(text)


class TextInputs:
    """Читает строки из stdin и передаёт их в обработчик как речь.

    Печатная команда не требует кодового слова: активацию берёт на себя
    submit_manual_text (дописывает триггер в конец строки).
    """

    EXIT_WORDS = frozenset(("выход", "exit", "quit"))

    def __init__(self, on_text: Callable[[str], None],
                 output: Optional[object] = None):
        self._on_text = on_text
        self._output = output

    def run(self) -> None:
        """Блокирующий цикл чтения; завершается на EOF или «выход»."""
        if not sys.stdin or not sys.stdin.isatty():
            if self._output is not None:
                self._output.print_info("[Text] stdin недоступен — ввод отключён")
            return
        if self._output is not None:
            self._output.print_info(
                "⌨️  Печатайте команды прямо (кодовое слово не нужно). "
                "«выход» — остановка.")
        while True:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt):
                return
            text = line.strip()
            if not text:
                continue
            if text.lower() in self.EXIT_WORDS:
                return
            self._on_text(text)
