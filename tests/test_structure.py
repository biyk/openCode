from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import generate_structure


def run_git(repo_root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")


def make_manifest(files: set[str], directories: set[str]) -> dict:
    return {
        "schema_version": 1,
        "exclusions": ["models/**", "__pycache__/**", "lib/__pycache__/**"],
        "files": {path: f"Описание файла {path}" for path in sorted(files)},
        "directories": {path: f"Описание каталога {path}" for path in sorted(directories)},
    }


def test_validate_manifest_accepts_complete_inventory() -> None:
    manifest = make_manifest(
        {"main.py", "lib/commands.py"},
        {".", "lib"},
    )

    errors = generate_structure.validate_manifest(
        manifest,
        {"main.py", "lib/commands.py"},
        {".", "lib"},
        manifest["exclusions"],
    )

    assert errors == []


def test_validate_manifest_reports_missing_descriptions() -> None:
    manifest = make_manifest(
        {"main.py"},
        {".", "lib"},
    )

    errors = generate_structure.validate_manifest(
        manifest,
        {"main.py", "lib/commands.py"},
        {".", "lib"},
        manifest["exclusions"],
    )

    assert "описание отсутствует для файла: lib/commands.py" in errors
    assert "описание отсутствует для каталога: lib" in errors


def test_validate_manifest_rejects_unknown_and_excluded_paths() -> None:
    manifest = make_manifest(
        {"main.py", "models/vosk.zip"},
        {".", "lib", "models"},
    )

    errors = generate_structure.validate_manifest(
        manifest,
        {"main.py"},
        {".", "lib"},
        manifest["exclusions"],
    )

    assert any("не найден в индексе" in error for error in errors)
    assert any("исключён из структуры" in error for error in errors)


def test_validate_manifest_requires_russian_description() -> None:
    manifest = make_manifest(
        {"main.py"},
        {".", "lib"},
    )
    manifest["files"]["main.py"] = "Entry point"

    errors = generate_structure.validate_manifest(
        manifest,
        {"main.py"},
        {".", "lib"},
        manifest["exclusions"],
    )

    assert any("на русском языке" in error for error in errors)


def test_render_structure_uses_descriptions_and_sorts_children() -> None:
    manifest = make_manifest(
        {"main.py", "lib/commands.py"},
        {".", "lib"},
    )

    rendered = generate_structure.render_structure(
        "voice",
        manifest,
        {"main.py", "lib/commands.py"},
        {".", "lib"},
    )

    assert "voice/  # Описание: Описание каталога ." in rendered
    assert "├── lib/  # Описание: Описание каталога lib" in rendered
    assert "│   └── commands.py  # Описание: Описание файла lib/commands.py" in rendered
    assert "└── main.py  # Описание: Описание файла main.py" in rendered


def test_render_document_replaces_generated_region() -> None:
    current = "# Структура\n\nСтарый текст\n"
    expected = "Новое дерево"

    rendered = generate_structure.render_document(current, expected)

    assert generate_structure.START_MARKER in rendered
    assert "Старый текст" in rendered
    assert "Новое дерево" in rendered
    assert "Старый текст\n```\n" not in rendered


def test_render_document_appends_region_when_missing() -> None:
    rendered = generate_structure.render_document("# Структура\n", "Дерево")

    assert rendered.endswith(generate_structure.END_MARKER + "\n")
    assert "Дерево" in rendered


def test_collect_index_uses_staged_tree_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")

    tracked = repo / "tracked.py"
    tracked.write_text("tracked", encoding="utf-8")
    run_git(repo, "add", "tracked.py")

    staged = repo / "staged.py"
    staged.write_text("staged", encoding="utf-8")
    run_git(repo, "add", "staged.py")

    unstaged = repo / "unstaged.py"
    unstaged.write_text("unstaged", encoding="utf-8")

    tracked.unlink()
    run_git(repo, "add", "-u")

    files = generate_structure.collect_index(repo)

    assert files == {"staged.py"}


def test_collect_index_excludes_deletes_and_ignores_unstaged_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init")

    deleted = repo / "deleted.py"
    deleted.write_text("deleted", encoding="utf-8")
    run_git(repo, "add", "deleted.py")
    deleted.unlink()
    run_git(repo, "add", "-u")

    ignored = repo / "ignored.log"
    ignored.write_text("log", encoding="utf-8")

    assert "deleted.py" not in generate_structure.collect_index(repo)
    assert "ignored.log" not in generate_structure.collect_index(repo)


def test_build_structure_fails_when_manifest_is_incomplete(tmp_path: Path) -> None:
    manifest_path = tmp_path / ".structure.json"
    manifest_path.write_text(
        json.dumps(make_manifest({"main.py"}, {"."})),
        encoding="utf-8",
    )

    with patch.object(
        generate_structure,
        "collect_index",
        return_value={"main.py", "lib/commands.py"},
    ), patch.object(
        generate_structure,
        "get_inferred_directories",
        return_value={".", "lib"},
    ):
        with pytest.raises(generate_structure.StructureError, match="lib/commands.py"):
            generate_structure.build_structure(tmp_path, manifest_path)


def test_main_check_accepts_current_structure(tmp_path: Path) -> None:
    structure_path = tmp_path / "STRUCTURE.md"
    structure_path.write_text("Новое дерево\n", encoding="utf-8")

    with patch.object(
        generate_structure,
        "build_structure",
        return_value="Новое дерево\n",
    ):
        assert generate_structure.main([
            "--check",
            "--manifest",
            str(tmp_path / ".structure.json"),
            "--structure",
            str(structure_path),
        ]) == 0


def test_main_check_rejects_stale_structure(tmp_path: Path) -> None:
    structure_path = tmp_path / "STRUCTURE.md"
    structure_path.write_text("Старое дерево\n", encoding="utf-8")

    with patch.object(
        generate_structure,
        "build_structure",
        return_value="Новое дерево\n",
    ):
        assert generate_structure.main([
            "--check",
            "--manifest",
            str(tmp_path / ".structure.json"),
            "--structure",
            str(structure_path),
        ]) == 1


def test_main_check_reports_missing_description(tmp_path: Path) -> None:
    structure_path = tmp_path / "STRUCTURE.md"
    structure_path.write_text("Дерево\n", encoding="utf-8")

    with patch.object(
        generate_structure,
        "build_structure",
        side_effect=generate_structure.StructureError("описание отсутствует"),
    ):
        assert generate_structure.main([
            "--check",
            "--manifest",
            str(tmp_path / ".structure.json"),
            "--structure",
            str(structure_path),
        ]) == 2


def test_main_write_updates_structure(tmp_path: Path) -> None:
    structure_path = tmp_path / "STRUCTURE.md"
    structure_path.write_text("Старое дерево\n", encoding="utf-8")

    with patch.object(
        generate_structure,
        "build_structure",
        return_value="Новое дерево\n",
    ):
        assert generate_structure.main([
            "--write",
            "--manifest",
            str(tmp_path / ".structure.json"),
            "--structure",
            str(structure_path),
        ]) == 0

    assert structure_path.read_text(encoding="utf-8") == "Новое дерево\n"


def test_main_stdout_prints_generated_tree(tmp_path: Path) -> None:
    with patch.object(
        generate_structure,
        "build_structure",
        return_value="Дерево\n",
    ):
        assert generate_structure.main([
            "--stdout",
            "--manifest",
            str(tmp_path / ".structure.json"),
        ]) == 0
