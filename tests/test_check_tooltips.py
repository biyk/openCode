# TOOLTIP: Тесты для проверки описаний файлов в .structure.json
from __future__ import annotations

from pathlib import Path

from scripts import check_tooltips


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_file_in_structure_json_passes(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    write(tmp_path / ".structure.json", '{"main.py": "точка входа"}')
    assert check_tooltips.validate(tmp_path) == []


def test_file_not_in_structure_json_fails(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    errors = check_tooltips.validate(tmp_path)
    assert any("main.py" in e for e in errors)


def test_main_returns_nonzero_on_missing(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    assert check_tooltips.main(["--root", str(tmp_path)]) == 1


def test_main_returns_zero_when_ok(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    write(tmp_path / ".structure.json", '{"main.py": "точка входа"}')
    assert check_tooltips.main(["--root", str(tmp_path)]) == 0


def test_structure_json_invalid_fails(tmp_path: Path) -> None:
    write(tmp_path / ".structure.json", "not json")
    try:
        check_tooltips.validate(tmp_path)
    except SystemExit:
        pass
    else:
        raise AssertionError("ожидался SystemExit на невалидный JSON")


def test_structure_json_missing_ok(tmp_path: Path) -> None:
    assert check_tooltips.validate(tmp_path) == []


def test_only_files_checked_dirs_ignored(tmp_path: Path) -> None:
    (tmp_path / "lib").mkdir()
    write(tmp_path / "main.py", "print('hello')\n")
    write(tmp_path / ".structure.json", '{"main.py": "точка входа"}')
    errors = check_tooltips.validate(tmp_path)
    assert errors == []


def test_all_files_must_be_described(tmp_path: Path) -> None:
    write(tmp_path / "a.py", "print(1)\n")
    write(tmp_path / "b.py", "print(2)\n")
    write(tmp_path / ".structure.json", '{"a.py": "файл A"}')
    errors = check_tooltips.validate(tmp_path)
    error_text = "\n".join(errors)
    assert "b.py" in error_text and "нет записи" in error_text
    assert not any("a.py" in e for e in errors)


def test_stale_entry_in_structure_json_fails(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    write(tmp_path / ".structure.json", '{"main.py": "точка входа", "gone.py": "удалён"}')
    errors = check_tooltips.validate(tmp_path)
    assert any("gone.py" in e and "не найден" in e for e in errors)


def test_excluded_files_are_not_required(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    write(tmp_path / "credentials.json", "{}")
    write(tmp_path / ".structure.json", '{"main.py": "точка входа"}')
    errors = check_tooltips.validate(tmp_path)
    assert not any("credentials.json" in e for e in errors)
