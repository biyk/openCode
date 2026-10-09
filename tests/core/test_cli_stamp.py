"""Гард: CLI-точки входа (`python -m lib.…`) печатают метки времени.

Команды исполняются дочерним процессом: у него свой stdout, обёртка из
main.py до него не доходит — без stamp_stdio() строки озвучки ([TTS]) и
итоги задач выходили в консоль без [ЧЧ:ММ:СС].

Исключения — модули, чей вывод разбирают построчно: метка в начале строки
сломала бы парсинг. Список с причинами ниже; тест проверяет и обратное —
что эти модули метки НЕ ставят.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_RE = re.compile(r"python -m (lib\.[\w.]+)")
_MAIN_RE = re.compile(r'^if __name__ == "__main__":', re.MULTILINE)

# Вывод разбирают построчно → метки им противоречат.
PARSED_OUTPUT = {
    "lib.browser_control":
        "cron-будильник wake_video_and_volume.ps1 сверяет последнюю строку "
        "вывода `eval` с 'playing'",
    "lib.tasks":
        "скилл task-complete разбирает строки task:/task_id:/result:",
    "lib.google_calendar":
        "скилл calendar-plans читает напечатанный список событий",
    "lib.voice_cmd.knowledge_review":
        "launch поднимает detached-сервер и тут же возвращает управление",
}


def _cli_modules():
    """Модули, которые конфиг команд или скиллы зовут как `python -m lib.…`."""
    files = list(REPO_ROOT.glob("targets/*/commands.json"))
    for pattern in (".opencode/skill/**/SKILL.md",
                    ".opencode/skill/**/*.md",
                    "cli/.opencode/skill/**/*.md"):
        files += list(REPO_ROOT.glob(pattern))
    found = set()
    for path in files:
        found |= set(_CLI_RE.findall(path.read_text(encoding="utf-8")))
    return sorted(found)


def _main_block(module: str) -> str:
    """Исходник модуля от `if __name__ == "__main__":` до конца файла."""
    source = (REPO_ROOT / f"{module.replace('.', '/')}.py").read_text(
        encoding="utf-8")
    match = _MAIN_RE.search(source)
    assert match, f"у {module} нет __main__ — непонятно, где ставить метки"
    return source[match.start():]


class TestCliStamp:
    """Каждый CLI с человеческим выводом зовёт stamp_stdio() в __main__."""

    @pytest.mark.parametrize("module", _cli_modules())
    def test_entry_point_stamps(self, module):
        if module in PARSED_OUTPUT:
            assert "stamp_stdio" not in _main_block(module), (
                f"{module} разбирается построчно ({PARSED_OUTPUT[module]}), "
                "метка времени сломала бы парсинг")
            return
        block = _main_block(module)
        assert "stamp_stdio()" in block, (
            f"{module} печатает в консоль без метки времени: "
            "в __main__ нужен вызов stamp_stdio() (lib/core/output.py)")
