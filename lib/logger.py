import os
from datetime import datetime
from pathlib import Path


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
