from datetime import datetime
from pathlib import Path
from typing import Optional


class Logger:
    """Логирование команд и переписки с LLM."""

    def __init__(self):
        self._base_dir = Path("logs")
        self._base_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._log_file = self._base_dir / f"commands_{timestamp}.log"
        self._llm_file = self._base_dir / f"llm_{timestamp}.log"

    def log_command(self, text: str):
        """Логирует распознанную команду с меткой времени."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {text}\n")

    def log_llm(self, role: str, content: str):
        """Логирует сообщение в переписке с LLM."""
        with open(self._llm_file, "a", encoding="utf-8") as f:
            f.write(f"[{role.upper()}] {content}\n")

    def get_llm_history(self, limit: int = 10) -> list[dict]:
        """Возвращает историю переписки с LLM из файла."""
        history = []
        if not self._llm_file.exists():
            return history

        with open(self._llm_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines[-limit:]:
            if line.startswith("[USER]"):
                history.append({"role": "user", "content": line[7:].strip()})
            elif line.startswith("[ASSISTANT]"):
                history.append({"role": "assistant", "content": line[11:].strip()})

        return history

    def log_info(self, message: str) -> None:
        """Логирует информационное сообщение в файл команд."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} [INFO] {message}\n")

    def log_error(self, message: str) -> None:
        """Логирует ошибку в файл команд."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self._log_file, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} [ERROR] {message}\n")


def latest_logs(base_dir: str = "logs") -> tuple[Optional[str], Optional[str]]:
    """Пути последних логов команд и чата (по mtime).

    Возвращает (commands_*.log, llm_*.log); отсутствующий — None.
    """
    base = Path(base_dir)
    commands_log = None
    llm_log = None
    if not base.is_dir():
        return None, None
    try:
        entries = [p for p in base.iterdir() if p.is_file()]
    except OSError:
        return None, None
    cmd = [p for p in entries if p.name.startswith("commands_")]
    llm = [p for p in entries if p.name.startswith("llm_")]
    if cmd:
        commands_log = str(max(cmd, key=lambda p: p.stat().st_mtime))
    if llm:
        llm_log = str(max(llm, key=lambda p: p.stat().st_mtime))
    return commands_log, llm_log


def tail_lines(path: str, limit: int) -> list[str]:
    """Последние limit строк файла (без концевых переносов)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return [line.rstrip("\r\n") for line in lines[-limit:] if line.strip()]


def read_llm_history(path: str, limit: int = 10) -> list[dict]:
    """История чата из llm-файла: [{'role', 'content'}], последние limit."""
    history = []
    for line in tail_lines(path, limit):
        if line.startswith("[USER]"):
            history.append({"role": "user", "content": line[6:].strip()})
        elif line.startswith("[ASSISTANT]"):
            history.append({"role": "assistant", "content": line[11:].strip()})
    return history
