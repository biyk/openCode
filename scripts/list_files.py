"""Генератор .structure.json через OmniRouter."""

import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scripts.files_git import (  # noqa: E402
    load_structure,
    iter_project_files,
    read_file_content,
    save_structure,
)
from scripts.files_ignore import STRUCTURE_FILE  # noqa: E402
from scripts.files_llm import request_description  # noqa: E402

ROOT = SCRIPT_ROOT


def process_file(relative_path: str, structure: dict) -> bool:
    """Обрабатывает один файл.

    Возвращает True, если файл был обработан.
    """

    if relative_path in structure:
        print(
            f"Пропуск: {relative_path} — "
            f"запись уже есть в .structure.json"
        )
        return False

    file_path = ROOT / relative_path

    print(f"Обрабатываю: {relative_path}")

    content = read_file_content(file_path)

    description = request_description(
        relative_path,
        content,
    )

    structure[relative_path] = description

    save_structure(
        ROOT / STRUCTURE_FILE,
        structure,
    )

    print(
        f"Готово: {relative_path} → {description}"
    )

    return True


def main() -> int:
    structure_path = ROOT / STRUCTURE_FILE

    structure = load_structure(
        structure_path
    )

    files = sorted(
        iter_project_files(ROOT),
        key=lambda p: p.as_posix().casefold(),
    )

    processed = 0
    skipped = 0
    failures = 0

    for relative_path in files:
        relative_posix = relative_path.as_posix()

        try:
            was_processed = process_file(
                relative_posix,
                structure,
            )

            if was_processed:
                processed += 1
            else:
                skipped += 1

        except Exception as error:
            failures += 1

            print(
                f"ОШИБКА: {relative_posix}: {error}"
            )

    print()
    print("===================================")
    print(f"Всего файлов:       {len(files)}")
    print(f"Обработано:         {processed}")
    print(f"Пропущено:          {skipped}")
    print(f"Ошибок:             {failures}")
    print("===================================")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
