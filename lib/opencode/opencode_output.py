"""Чистка вывода console opencode (миксин раннера)."""

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# Открывающие блоки агента, которые режем целиком (до закрывающего тега)
_BLOCK_OPEN_RE = re.compile(r"^\s*<(parameter|system-reminder|function|supply)")


def _strip_ansi(text: str) -> str:
    """Убирает ANSI-управляющие последовательности из вывода."""
    return _ANSI_RE.sub("", text)


class OpenCodeOutputMixin:
    """Миксин OpenCodeCliRunner: дамп частичного вывода и чистка."""

    def _dump_partial(self, chunks: list[str], verbose: bool) -> None:
        """Показывает накопленный вывод CLI при таймауте (dev-режим)."""
        raw = _strip_ansi("".join(chunks))
        if not raw.strip():
            return
        if verbose:
            self._output.print_info(
                "[OpenCode] Вывод до таймаута:")
            for line in raw.splitlines():
                text_line = line.rstrip("\r\n")
                if text_line.strip():
                    self._output.print_info(f"[OpenCode>>] {text_line}")
        else:
            self._output.print_debug(
                f"[OpenCode] Вывод до таймаута:\n{raw}")

    def _clean(self, output: str) -> str:
        """Причёсывает вывод: ANSI, пустые подсказки, мусорные строки.

        Также отбрасывает технический шум агента: заголовки «> build»,
        спиннеры, вызовы несуществующих инструментов («No tool named ...»),
        JSON-параметры «<parameter=...>», «Arguments provided:». В итоге
        остаётся читаемый ответ, который и печатается в консоль.
        """
        raw = _strip_ansi(output)
        lines = []
        in_block = False
        for line in raw.splitlines():
            text = line.rstrip("\r\n")
            if not in_block and _BLOCK_OPEN_RE.match(text):
                # Выбрасываем весь блок агента до </...>
                in_block = True
                continue
            if in_block:
                if "</" in text or text.rstrip().endswith("/>"):
                    in_block = False
                continue
            if not self._is_noise_line(text):
                lines.append(text)
        # Схлопнуть повторные пустые строки
        cleaned = []
        for text in lines:
            if not text.strip() and cleaned and not cleaned[-1].strip():
                continue
            cleaned.append(text)
        return "\n".join(cleaned).strip() or None

    @staticmethod
    def _is_noise_line(text: str) -> bool:
        """Техническая ли шумовая строка вывода агента."""
        s = text.strip()
        if not s:
            return True
        low = s.lower()
        if low in (">", "thinking...", "accepting request for model update..."):
            return True
        if s.startswith("⠙") or s.startswith("⣾"):
            return True
        # Заголовки, стрелки, проваленные вызовы инструментов
        if s.startswith(">") or s.startswith("→") or s.startswith("✗"):
            return True
        # «$ cd C:\...; python -c ...» — исполняемые команды, не ответ
        if s.startswith("$"):
            return True
        # Ошибки агента про неизвестные инструменты/аргументы
        if "no tool named" in low or "invalid arguments for tool" in low:
            return True
        if "arguments provided" in low or "update the arguments" in low:
            return True
        if s == "{" or s == "}" or s == "}":
            return True
        # JSON-параметры («"filePath": "..."», «- path: Missing key»)
        if s.startswith('"') and ":" in s:
            return True
        if re.match(r"^-\s+\w+:", s):
            return True
        # Открытые блоки агента: <system-reminder>, <parameter=...>, <function>
        if s.startswith("<parameter") or s.startswith("<system-reminder") \
                or s.startswith("<function"):
            return True
        if s.startswith("</parameter") or s.startswith("</system-reminder") \
                or s.startswith("</function"):
            return True
        # Tool-call разметка агента, выведенная текстом (Anthropic/Claude):
        # <|tool| calls>, <|invoke ...>, <|parameter ...>, </|invoke>, </|calls>
        # — с обычным пайпом «|» или полной ширины «｜».
        if re.match(r"^</?[|｜][^>]*>", s):
            return True
        return False
