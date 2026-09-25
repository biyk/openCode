"""Обработчик голосовых команд задач («добавь задачу …», «заверши задачу …»).

Создание: связывает распознанный текст («добавь задачу: купить хлеб») с
Google Tasks через lib.google_tasks: текст без триггера становится
названием задачи в списке по умолчанию.

Завершение: «заверши задачу купить хлеб» загружает незавершённые задачи,
ищет по названию и отмечает совпадения выполненными.

Разбор детерминированный; LLM (Laya) используется только для проверки
на дубликат перед созданием: строгое совпадание — пропускаем, иначе
спрашиваем модель, и если дубликата нет — создаём.
"""

import base64
import json
import platform
import sys
from typing import Optional

from lib import tasks_dedup
from lib.commands import CommandMatcher
from lib.config_loader import get_device_commands_path
from lib.google_tasks import GoogleOAuthError, GoogleTasks
from lib.laya_decision import LayaDecision
from lib.tasks_complete import TaskCompleteMixin
from lib.tasks_parse import TRIGGER_PHRASES, _canonicalize, _clean_candidate
from lib.tts import TextToSpeech


class TaskHandler(TaskCompleteMixin):
    """Определяет, является ли текст командой задачи, и создаёт/завершает её."""

    def __init__(
        self,
        google: Optional[GoogleTasks] = None,
    ) -> None:
        self._google = google or GoogleTasks()

    def is_task(self, text: str) -> bool:
        """Начинается ли текст с триггерной фразы задачи."""
        t = _canonicalize(text)
        return any(t.startswith(p) for p in TRIGGER_PHRASES)

    def create(self, text: str) -> Optional[str]:
        """Извлекает название задачи из фразы.

        Возвращает очищенный текст после триггера; None для пустой фразы.
        """
        return _clean_candidate(text) or None

    def add_task(self, title: str, notes: Optional[str] = None) -> Optional[str]:
        """Создаёт задачу в Google Tasks через API.

        Возвращает id задачи или None при неудаче.
        """
        try:
            return self._google.create_task(title=title, notes=notes)
        except Exception as e:
            print(f"[Google] Ошибка создания задачи: {e}")
            return None

    def auth_ready(self) -> bool:
        """Готовы ли авторизация и scope для Google Tasks."""
        return self._google.is_ready()

    def find_duplicate(self, title: str) -> Optional[dict]:
        """Есть ли в списке уже такая же задача (exact, затем Laya).

        Возвращает {"id", "title", "method"} дубликата или None.
        """
        try:
            existing = self._google.list_tasks(show_completed=False)
        except Exception as e:
            print(f"[Google] Ошибка загрузки задач (проверка дублей): {e}")
            return None
        return tasks_dedup.find_duplicate(
            title, existing, get_laya_decision)

    def authorize(self) -> None:
        """Обновляет доступ (refresh) или проходит интерактивный OAuth.

        Бросает GoogleOAuthError, если авторизоваться не удалось.
        """
        self._google.authorize()


def get_laya_decision() -> Optional[LayaDecision]:
    """Клиент Laya из commands.json или None (сервер не запускаем).

    subprocess не должен поднимать модель: если готового сервера нет,
    дубликат ищем только строгим совпадением.
    """
    try:
        path = get_device_commands_path(platform.node())
        config = CommandMatcher(path).get_decision_config()
        if not config.get("enabled"):
            return None
        client = LayaDecision(config)
        return client if client.available else None
    except Exception:
        return None


def _decode_arg(raw: str) -> str:
    """Декодирует аргумент CLI: --b64:<base64> или обычный текст.

    base64 допускается (кириллица/кавычки в консоли), но НЕ обязателен:
    обычная фраза аргументом доходит как есть. Терпим к url-safe алфавиту
    (-_) и отсутствию паддинга.
    """
    raw = raw.strip()
    if raw.startswith("--b64:") or raw.startswith("--b64="):
        payload = raw.split(":", 1)[1] if ":" in raw[:6] else raw[6:]
        try:
            padded = payload.translate(str.maketrans("-_", "+/"))
            padded += "=" * (-len(padded) % 4)
            return base64.b64decode(padded).decode("utf-8")
        except Exception:
            return raw
    return raw


def main(argv: Optional[list] = None) -> int:
    """CLI: `python -m lib.tasks complete <фраза>` / `create <фраза>`
    (или `... --b64:<base64>`).

    complete — выполняет задачу по названию (complete_matching) и печатает
    отчёт в stdout. Используется скиллом task-complete в консольном
    opencode — единая короткая команда вместо фрагмента python -c.
    create — создаёт задачу (текст после триггера — название) в списке
    по умолчанию. Используется командой task-add из commands.json.
    Коды: 0 — ок, 1 — ошибка API, 2 — неверные аргументы,
    3 — пустая фраза или нет авторизации Tasks.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in ("complete", "create"):
        print("usage: python -m lib.tasks complete <фраза> | "
              "create <фраза> | --b64:<base64>")
        return 2
    if len(args) < 2:
        print(f"usage: python -m lib.tasks {args[0]} <фраза>")
        return 2
    phrase = " ".join(_decode_arg(a) for a in args[1:])
    try:
        handler = TaskHandler()
        if args[0] == "create":
            title = handler.create(phrase)
            if not title:
                print("Пустая фраза — нечего создавать")
                return 3
            try:
                # Протухший токен обновляется здесь же (refresh); без
                # авторизации — интерактивный OAuth в браузере.
                handler.authorize()
            except GoogleOAuthError as e:
                print(f"[Google] Нет авторизации Tasks: {e}")
                return 3
            dup = handler.find_duplicate(title)
            if dup:
                print("task:", title)
                print("duplicate:", json.dumps(dup, ensure_ascii=False))
                print(f"Такая задача уже стоит: «{dup['title']}» "
                      f"({dup['method']}) — пропускаем")
                return 0
            task_id = handler.add_task(title)
            if not task_id:
                print("Не удалось создать задачу")
                return 1
            print("task:", title)
            print("task_id:", task_id)
            try:
                TextToSpeech().speak_and_play("Готово")
            except Exception as e:
                print(f"[Voice] Озвучка не удалась: {e}")
            return 0
        title = handler.complete_parse(phrase) or ""
        if not title:
            print("title: <пусто>")
            print("result: \"matched\": []")
            return 3
        result = handler.complete_matching(title)
        print("title:", title)
        print("result:", json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
