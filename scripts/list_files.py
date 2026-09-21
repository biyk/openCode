import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "models",
}

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".pyo",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".lock",
}

IGNORED_FILENAMES = {
    "VERSION",
}

STRUCTURE_FILE = ".structure.json"

OMNIROUTER_URL = "http://localhost:20128/v1/chat/completions"
MODEL = "auto"

TIMEOUT_SECONDS = 300


def is_ignored_extension(path: Path) -> bool:
    return path.suffix.lower() in IGNORED_EXTENSIONS


def is_ignored_filename(path: Path) -> bool:
    return path.name in IGNORED_FILENAMES


def iter_project_files(root: Path):
    """
    Получает список отслеживаемых Git файлов.
    """

    process = __import__("subprocess").run(
        ["git", "ls-files", "-z", "--"],
        cwd=root,
        stdout=__import__("subprocess").PIPE,
        stderr=__import__("subprocess").PIPE,
        check=False,
    )

    if process.returncode != 0:
        raise RuntimeError(
            process.stderr.decode("utf-8", errors="replace").strip()
            or "не удалось получить список файлов из git"
        )

    for encoded_path in process.stdout.split(b"\0"):
        if not encoded_path:
            continue

        relative_path = Path(
            encoded_path.decode("utf-8", errors="surrogateescape")
        )

        relative_posix = relative_path.as_posix()

        if relative_posix == STRUCTURE_FILE:
            continue

        if any(part in IGNORED_DIRECTORIES for part in relative_path.parts):
            continue

        if is_ignored_filename(relative_path):
            print(
                f"Пропуск файла с исключённым именем: "
                f"{relative_posix}"
            )
            continue

        if is_ignored_extension(relative_path):
            print(
                f"Пропуск файла с исключённым расширением: "
                f"{relative_posix}"
            )
            continue

        yield relative_path


def load_structure(path: Path) -> dict:
    """
    Загружает .structure.json.

    Если файла нет — возвращает пустой объект.
    """

    if not path.exists():
        return {}

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as error:
        raise RuntimeError(
            f"Не удалось прочитать {path}: {error}"
        ) from error

    if not isinstance(data, dict):
        raise RuntimeError(
            f"{path} должен содержать JSON-объект"
        )

    return data


def save_structure(path: Path, structure: dict):
    """
    Сохраняет .structure.json.
    """

    path.write_text(
        json.dumps(
            structure,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def read_file_content(path: Path) -> str:
    """
    Читает содержимое файла как UTF-8 текст.

    Для исходников, сохранённых с другой кодировкой,
    повреждённые байты заменяются символом �.
    """

    return path.read_bytes().decode(
        "utf-8",
        errors="replace",
    )


def build_messages(relative_path: str, content: str) -> list:
    return [
        {
            "role": "system",
            "content": (
                "Ты анализируешь структуру программного проекта. "
                "Для каждого файла нужно определить, что это за файл "
                "и зачем он нужен проекту. "
                "Верни только одно предложение на русском языке. "
                "Без Markdown, без кавычек, без списка, без пояснений "
                "и без нескольких предложений."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Путь к файлу:\n"
                f"{relative_path}\n\n"
                f"Содержимое файла:\n"
                f"{content}\n\n"
                f"Опиши этот файл одним предложением: "
                f"что это за файл и для чего он нужен."
            ),
        },
    ]


def request_description(relative_path: str, content: str) -> str:
    """
    Отправляет путь и содержимое файла напрямую в OmniRouter.
    """

    payload = {
        "model": MODEL,
        "messages": build_messages(
            relative_path,
            content,
        ),
        "temperature": 0.2,
    }

    request = urllib.request.Request(
        OMNIROUTER_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT_SECONDS,
        ) as response:
            raw_response = response.read().decode(
                "utf-8",
                errors="replace",
            )

    except urllib.error.HTTPError as error:
        error_body = error.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"OmniRouter HTTP {error.code}: {error_body}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Не удалось подключиться к OmniRouter: {error.reason}"
        ) from error

    except TimeoutError as error:
        raise RuntimeError(
            f"Таймаут обращения к OmniRouter: "
            f"{TIMEOUT_SECONDS} сек"
        ) from error

    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"OmniRouter вернул некорректный JSON:\n"
            f"{raw_response[:2000]}"
        ) from error

    try:
        description = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(
            "Не удалось получить description из ответа OmniRouter:\n"
            f"{json.dumps(data, ensure_ascii=False)[:3000]}"
        ) from error

    if not isinstance(description, str):
        raise RuntimeError(
            "OmniRouter вернул описание не в виде строки"
        )

    return description.strip()


def process_file(relative_path: str, structure: dict) -> bool:
    """
    Обрабатывает один файл.

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
