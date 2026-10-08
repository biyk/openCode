# TOOLTIP: Тесты BOM-гейта для .ps1 (PS 5.1 не переваривает кириллицу без BOM)
from __future__ import annotations

from pathlib import Path

from scripts import check_ps1_bom

BOM = b"\xef\xbb\xbf"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_pure_ascii_no_bom_passes(tmp_path: Path) -> None:
    _write(tmp_path / "clean.ps1", b'Write-Host "hi"\n')
    assert check_ps1_bom.validate(tmp_path) == []


def test_cyrillic_with_bom_passes(tmp_path: Path) -> None:
    text = "# Привет\nWrite-Host \"тест\"\n"
    _write(tmp_path / "ru.ps1", BOM + text.encode("utf-8"))
    assert check_ps1_bom.validate(tmp_path) == []


def test_cyrillic_without_bom_fails(tmp_path: Path) -> None:
    text = "# Привет\nWrite-Host \"тест\"\n"
    _write(tmp_path / "ru_no_bom.ps1", text.encode("utf-8"))
    errors = check_ps1_bom.validate(tmp_path)
    assert any(
        "ru_no_bom.ps1" in e and "BOM" in e for e in errors
    ), f"ожидали сигнал по ru_no_bom.ps1, получили: {errors}"


def test_bom_body_must_be_utf8(tmp_path: Path) -> None:
    # BOM есть, а тело — cp1251 байты «Привет» (классический mojibake).
    body = b"# \xcf\xf0\xe8\xe2\xe5\xf2\n"
    _write(tmp_path / "mojibake.ps1", BOM + body)
    errors = check_ps1_bom.validate(tmp_path)
    assert any(
        "mojibake.ps1" in e and "UTF-8" in e for e in errors
    ), f"ожидали жалобу на декодирование UTF-8, получили: {errors}"


def test_guilettes_non_ascii_triggers_bom(tmp_path: Path) -> None:
    # Не только кириллица: « » — тоже > 0x7F и тоже ломают PS 5.1 без BOM.
    text = '# «тест»\n'
    _write(tmp_path / "quotes.ps1", text.encode("utf-8"))
    errors = check_ps1_bom.validate(tmp_path)
    assert any("quotes.ps1" in e for e in errors), errors


def test_non_ps1_files_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "notes.txt", "Привет".encode("utf-8"))
    _write(tmp_path / "code.py", "# Привет\n".encode("utf-8"))
    assert check_ps1_bom.validate(tmp_path) == []


def test_excluded_dirs_ignored(tmp_path: Path) -> None:
    body = "привет".encode("utf-8")  # кириллица без BOM
    _write(tmp_path / "venv" / "x.ps1", body)
    _write(tmp_path / "temp" / "y.ps1", body)
    _write(tmp_path / "logs" / "z.ps1", body)
    _write(tmp_path / ".voice-cdp-profile-9222" / "w.ps1", body)
    assert check_ps1_bom.validate(tmp_path) == []


def test_check_file_returns_problems_list(tmp_path: Path) -> None:
    path = tmp_path / "broken.ps1"
    _write(path, "привет".encode("utf-8"))
    problems = check_ps1_bom.check_file(path)
    assert problems, "check_file обязан вернуть непустой список"
    assert "BOM" in problems[0]


def test_check_file_ok_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "ok.ps1"
    _write(path, BOM + "привет".encode("utf-8"))
    assert check_ps1_bom.check_file(path) == []


def test_check_file_unreadable_reports(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.ps1"
    problems = check_ps1_bom.check_file(missing)
    assert problems and "не читается" in problems[0]


def test_main_returns_zero_when_ok(tmp_path: Path) -> None:
    _write(tmp_path / "clean.ps1", b'Write-Host "hi"\n')
    assert check_ps1_bom.main(["--root", str(tmp_path)]) == 0


def test_main_returns_one_on_missing_bom(tmp_path: Path) -> None:
    _write(tmp_path / "bad.ps1", "кириллица".encode("utf-8"))
    assert check_ps1_bom.main(["--root", str(tmp_path)]) == 1


def test_repo_is_clean() -> None:
    """Реальный репозиторий обязан проходить BOM-гейт.

    Ловит тот же класс регресса, что сломал будильник: любой следующий
    SearchReplace, потерявший BOM у wake_video_and_volume.ps1 или
    bin/get_volume.ps1, уронит этот тест раньше, чем cron попытается
    запустить скрипт и упадёт на PS-парсере.
    """
    root = Path(__file__).resolve().parents[1]
    errors = check_ps1_bom.validate(root)
    assert not errors, "BOM-гейт нашёл проблемы: " + "; ".join(errors)
