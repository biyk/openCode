# TOOLTIP: Тесты проверки, что файлы исходников не длиннее лимита строк
from __future__ import annotations

from pathlib import Path

from scripts import check_lengths


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_short_python_file_passes(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    assert check_lengths.validate(tmp_path) == []


def test_long_python_file_fails(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "\n".join(f"x{i} = 1" for i in range(201)))
    errors = check_lengths.validate(tmp_path)
    assert any("main.py" in e and "201" in e for e in errors)


def test_ps1_file_checked(tmp_path: Path) -> None:
    write(tmp_path / "run.ps1", "\n".join(f"Write-Host {i}" for i in range(201)))
    errors = check_lengths.validate(tmp_path)
    assert any("run.ps1" in e for e in errors)


def test_bat_and_sh_checked(tmp_path: Path) -> None:
    write(tmp_path / "run.bat", "\n".join("echo hi" for _ in range(201)))
    write(tmp_path / "run.sh", "\n".join("# hi" for _ in range(201)))
    errors = check_lengths.validate(tmp_path)
    assert any("run.bat" in e for e in errors)
    assert any("run.sh" in e for e in errors)


def test_exactly_limit_passes(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "\n".join(f"x{i} = 1" for i in range(100)))
    assert check_lengths.validate(tmp_path, limit=100) == []


def test_custom_limit(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "\n".join(f"x{i} = 1" for i in range(101)))
    errors = check_lengths.validate(tmp_path, limit=100)
    assert any("101" in e for e in errors)


def test_non_code_files_ignored(tmp_path: Path) -> None:
    write(tmp_path / "notes.txt", "\n".join("abyrvalg" for _ in range(300)))
    write(tmp_path / "data.json", "\n".join("{}" for _ in range(300)))
    assert check_lengths.validate(tmp_path) == []


def test_excluded_dirs_ignored(tmp_path: Path) -> None:
    write(tmp_path / "venv" / "main.py", "\n".join(f"x{i} = 1" for i in range(300)))
    assert check_lengths.validate(tmp_path) == []


def test_main_returns_zero_when_ok(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "print('hello')\n")
    assert check_lengths.main(["--root", str(tmp_path)]) == 0


def test_main_returns_one_on_long_file(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "\n".join(f"x{i} = 1" for i in range(300)))
    assert check_lengths.main(["--root", str(tmp_path)]) == 1


def test_main_respects_custom_limit(tmp_path: Path) -> None:
    write(tmp_path / "main.py", "\n".join(f"x{i} = 1" for i in range(150)))
    assert check_lengths.main(["--root", str(tmp_path), "--limit", "100"]) == 1
    assert check_lengths.main(["--root", str(tmp_path)]) == 0
