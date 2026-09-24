"""Запрос описаний файлов в OmniRouter."""

import json
import urllib.error
import urllib.request

OMNIROUTER_URL = "http://localhost:20128/v1/chat/completions"
MODEL = "auto"

TIMEOUT_SECONDS = 300


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
    """Отправляет путь и содержимое файла напрямую в OmniRouter."""

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
