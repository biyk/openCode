# TOOLTIP: Тесты проверки новых слепых except Exception
from __future__ import annotations

from pathlib import Path

from scripts import check_blind_except as cbe


def test_silent_except_is_violation() -> None:
    src = "try:\n    f()\nexcept Exception:\n    return False\n"
    lines = [n for n, _ in cbe.find_blind_excepts(src)]
    assert lines == [3]


def test_except_with_print_passes() -> None:
    src = "try:\n    f()\nexcept Exception as e:\n    print(e)\n    return []\n"
    assert cbe.find_blind_excepts(src) == []


def test_except_with_swallowed_passes() -> None:
    src = ("try:\n    f()\nexcept Exception as e:\n"
           "    return swallowed('x.y', e, False)\n")
    assert cbe.find_blind_excepts(src) == []


def test_blind_ok_marker_passes() -> None:
    src = "try:\n    f()\nexcept Exception:  # blind-ok: проба статуса\n    pass\n"
    assert cbe.find_blind_excepts(src) == []


def test_typed_except_not_blind() -> None:
    src = "try:\n    f()\nexcept queue.Empty:\n    break\n"
    assert cbe.find_blind_excepts(src) == []


def test_bare_except_counted() -> None:
    src = "try:\n    f()\nexcept:\n    pass\n"
    assert len(cbe.find_blind_excepts(src)) == 1


def test_validate_paths_reports_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("try:\n    f()\nexcept Exception:\n    pass\n",
                   encoding="utf-8")
    errors = cbe.validate_paths(tmp_path, ["bad.py"])
    assert any("bad.py:3" in e for e in errors)


def test_main_git_clean_on_untouched_repo() -> None:
    # Нет staged-.py — нет и ошибок.
    assert cbe.main(["--git"]) == 0
