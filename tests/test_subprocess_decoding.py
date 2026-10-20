# TOOLTIP: Страж: у каждого текстового subprocess-вызова явно названа encoding
"""Почему декодирование вывода дочернего процесса должно быть явным.

`text=True` без `encoding=` берёт кодировку процесса. В обычном запуске это
системная cp866/cp1251 — и всё работает. В `-X utf8` (или `PYTHONUTF8=1`) это
UTF-8, а wmic/git/powershell печатают вывод своей кодировкой: декодирование
падает в reader-потоке subprocess, исключение из него никуда не доходит, а
`stdout`/`stderr` приходят **None**. Дальше `None.splitlines()` в
`tests/resurrector_control.py` ронял фикстуру live-сессии — и весь прогон
превращался в 2130 одинаковых ошибок вместо одного сломавшегося теста.

Тот же дефект маскировался в живых тестах: сообщение об ошибке строится из
`res.stderr.strip()`, и на None падало не сравнение, а форматирование текста
ошибки — прогон валился с невнятным AttributeError вместо причины.
"""

import ast
import subprocess

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Методы subprocess, у которых есть текстовый режим.
SUBPROCESS_METHODS = ("run", "Popen", "check_output", "check_call")
TEXT_KWARGS = ("text", "universal_newlines")
# Минимум текстовых вызовов, который обязан увидеть скан: иначе страж слепнет
# (переименовали метод, переехали файлы — и правило молча перестало что-то
# проверять). Сейчас их 14 с лишним; порог ниже, чтобы правка не ломала тест.
EXPECTED_CALLS_MIN = 8


def _text_mode_calls(path: Path):
    """Вызовы subprocess в текстовом режиме: (номер строки, имена keyword)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute)
                and func.attr in SUBPROCESS_METHODS):
            continue
        names = {kw.arg for kw in node.keywords if kw.arg}
        if names & set(TEXT_KWARGS):
            yield node.lineno, names


def _sources():
    """Все .py-файлы lib/ и tests/ (без служебных кэшей)."""
    for root in ("lib", "tests"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


class TestTextModeNamesEncoding:
    """Каждый текстовый запуск дочернего процесса сам говорит, как читать."""

    def test_no_bare_text_mode(self):
        bad = []
        seen = 0
        for path in _sources():
            for lineno, names in _text_mode_calls(path):
                seen += 1
                if "encoding" not in names:
                    rel = path.relative_to(REPO_ROOT)
                    bad.append(f"{rel}:{lineno}")
        assert not bad, (
            "text=True без `encoding=` — в UTF-8-режиме вывод не декодируется "
            "и stdout приходит None: " + ", ".join(bad))
        assert seen >= EXPECTED_CALLS_MIN, (
            f"текстовых вызовов найдено {seen} — скан слепнет, проверь "
            "SUBPROCESS_METHODS и пути")


class TestUnreadableOutputIsAVerdict:
    """Помощник live-сессии на недекодируемом выводе — None, не AttributeError.

    Именно здесь молчаливый `stdout=None` превращался в 2130 ошибок прогона:
    вердикт «определить не вышло» обязан остаться вердиктом, а не падением.
    """

    def _patch_run(self, monkeypatch, stdout):
        from tests import resurrector_control as rc

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=stdout,
                                               stderr="")

        monkeypatch.setattr(rc.subprocess, "run", fake_run)
        return rc

    def test_none_stdout_is_not_crash(self, monkeypatch):
        rc = self._patch_run(monkeypatch, None)
        assert rc._main_app_pids() is None

    def test_cyrillic_bytes_still_yield_pids(self, monkeypatch):
        """cp1251-строка wmic не должна топить разбор: PID и путь — ASCII."""
        line = "NODE,CommandLine,ProcessId\r\n"
        line += "NODE,python.exe C:\\repo\\main.py,4280\r\n"
        line += "NODE,юзер\\python.exe C:\\рабочий\\main.py,4281\r\n"
        line += "NODE,python.exe other.py,4282\r\n"
        rc = self._patch_run(monkeypatch, line.encode("cp1251"))
        assert rc._main_app_pids() == [4280, 4281]
