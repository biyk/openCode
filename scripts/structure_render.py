"""Рендер дерева проекта для STRUCTURE.md."""

from typing import Any

from scripts.structure_common import _description_for, _normalize_path

START_MARKER = "STRUCTURE:START"
END_MARKER = "STRUCTURE:END"


def render_structure(
    root_name: str,
    manifest: dict[str, Any],
    files: set[str],
    directories: set[str],
) -> str:
    """Рендерит дерево проекта в строку Markdown."""
    files = {_normalize_path(path) for path in files}
    directories = {_normalize_path(path) for path in directories}
    root_name = root_name.replace("\\", "/").rstrip("/")

    children_dirs: dict[str, list[str]] = {}
    children_files: dict[str, list[str]] = {}
    for directory in directories:
        if directory == ".":
            continue
        parent = directory.rpartition("/")[0] or "."
        children_dirs.setdefault(parent, []).append(directory)
    for path in files:
        parent = path.rpartition("/")[0] or "."
        children_files.setdefault(parent, []).append(path)

    root_description = _description_for(manifest, ".")
    root_line = root_name + (f"  # {root_description}" if root_description else "")
    lines = [root_line]

    def append_entry(prefix: str, connector: str, path: str, is_directory: bool) -> None:
        name = path.rpartition("/")[2] if "/" in path else path
        label = f"{name}/" if is_directory else name
        description = _description_for(manifest, path)
        suffix = f"  # {description}" if description else ""
        lines.append(f"{prefix}{connector}{label}{suffix}")

    def walk(parent: str, prefix: str) -> None:
        entries = [(path, True) for path in sorted(children_dirs.get(parent, []))]
        entries += [(path, False) for path in sorted(children_files.get(parent, []))]
        for index, (path, is_directory) in enumerate(entries):
            is_last = index == len(entries) - 1
            connector = "└── " if is_last else "├── "
            append_entry(prefix, connector, path, is_directory)
            if is_directory:
                next_prefix = prefix + ("    " if is_last else "│   ")
                walk(path, next_prefix)

    walk(".", "")
    return "\n".join(lines)


def render_document(current: str, expected: str) -> str:
    """Заменяет сгенерированную область в текущем содержимом STRUCTURE.md."""
    start_marker = f"## {START_MARKER}"
    end_marker = f"## {END_MARKER}"
    region = f"{start_marker}\n```\n{expected.rstrip()}\n```\n{end_marker}"

    start_idx = current.find(start_marker)
    end_idx = current.find(end_marker)
    if start_idx != -1 and end_idx != -1:
        prefix = current[:start_idx].rstrip()
        suffix = current[end_idx + len(end_marker):]
        result = f"{prefix}\n\n{region}" if prefix else region
        if suffix.strip():
            result += "\n" + suffix.strip() + "\n"
        else:
            result += "\n"
        return result

    separator = "\n\n" if current.strip() else ""
    return current.rstrip() + separator + region + "\n"
