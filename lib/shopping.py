"""Голосовые команды списка покупок: «нужно купить X» / «купил X».

add    — новая строка в лист «Список покупок» (товар + дата добавления),
bought — поиск строки по названию и удаление её из таблицы,
list   — напечатать список (проверить результат руками).

Таблица и режим поиска дубликатов описаны секцией `shopping` в
commands.json устройства; сам дедуп (lib.google.shopping_dedup) пока
выключен флагом `shopping.dedup.enabled=false` — оставлен на будущее.

Запуск:
    python -m lib.shopping add "молоко"
    python -m lib.shopping bought "молоко"
"""

import platform
import re
import sys
from datetime import datetime
from typing import Any, Optional

from lib.google.shopping_dedup import find_duplicate, find_item
from lib.google.shopping_sheet import (
    SHEET_ID, SHEET_NAME, SPREADSHEET_ID, ShoppingSheet)
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path

# Хвостовая пунктуация распознавателя: «молоко.» → «молоко»
_TRAILING_RE = re.compile(r"[\s.,!?;:]+$")
STAMP_FORMAT = "%d.%m.%Y %H:%M"


def clean_item(text: str) -> str:
    """Название товара из фразы: пробелы в один, без хвостовой точки."""
    name = " ".join((text or "").split())
    return _TRAILING_RE.sub("", name).strip()


def _as_dict(config: Any) -> dict:
    """Переданный конфиг: None/не словарь — пустой словарь (дефолты)."""
    return config if isinstance(config, dict) else {}


def load_shopping_config() -> dict:
    """Секция `shopping` из commands.json устройства (пусто — дефолты)."""
    try:
        path = get_device_commands_path(platform.node())
        return CommandMatcher(path).get_shopping_config()
    except Exception:
        return {}


class ShoppingHandler:
    """Добавляет и удаляет позиции списка покупок в Google Таблице."""

    def __init__(self, sheet: Any = None, config: Optional[dict] = None,
                 now: Optional[datetime] = None) -> None:
        cfg = load_shopping_config() if config is None else _as_dict(config)
        self.config = cfg
        self.dedup = cfg.get("dedup") or {}
        self.now = now
        self.sheet = sheet or ShoppingSheet(
            spreadsheet_id=cfg.get("spreadsheet_id") or SPREADSHEET_ID,
            sheet_name=cfg.get("sheet_name") or SHEET_NAME,
            sheet_id=int(cfg.get("sheet_id") or SHEET_ID))

    def add_item(self, name: str) -> dict:
        """«нужно купить {товар}»: строка в конец списка."""
        item = clean_item(name)
        if not item:
            return {"ok": False, "action": "add",
                    "error": "пустое название товара"}
        dup = find_duplicate(item, self.sheet.items(), self.dedup)
        if dup is not None:
            return {"ok": True, "action": "add", "duplicate": True,
                    "item": dup["name"], "row": dup["row"],
                    "method": dup["method"]}
        self.sheet.ensure_header()
        row = self.sheet.append_item(item, self.stamp())
        return {"ok": True, "action": "add", "item": item, "row": row}

    def buy_item(self, name: str) -> dict:
        """«купил {товар}»: найти позицию и удалить её из таблицы."""
        item = clean_item(name)
        if not item:
            return {"ok": False, "action": "buy",
                    "error": "пустое название товара"}
        match = find_item(item, self.sheet.items(), self.dedup)
        if match is None:
            return {"ok": False, "action": "buy",
                    "error": f"«{item}» в списке покупок не найдено"}
        self.sheet.delete_row(match["row"])
        return {"ok": True, "action": "buy", "item": match["name"],
                "row": match["row"], "method": match["method"]}

    def list_items(self) -> dict:
        """Текущий список (для проверки руками и для озвучки)."""
        return {"ok": True, "action": "list",
                "items": [it["name"] for it in self.sheet.items()]}

    def stamp(self) -> str:
        """Дата/время добавления в колонку B (локаль ru, текст)."""
        now = self.now or datetime.now()
        return now.strftime(STAMP_FORMAT)


def _report(result: dict) -> None:
    """Печатает итог операции парами «ключ: значение» (как lib.tasks)."""
    print("action:", result.get("action", ""))
    if result.get("ok"):
        print("shop:", "duplicate" if result.get("duplicate")
              else "list" if result.get("action") == "list" else "ok")
        if "item" in result:
            print("item:", result["item"])
        if result.get("row") is not None:
            print("row:", result["row"])
        if result.get("items") is not None:
            print("items:", ", ".join(result["items"]) or "(список пуст)")
        return
    print("shop: error")
    print("reason:", result.get("error", ""))


def main(argv: Optional[list] = None) -> int:
    """CLI: `python -m lib.shopping add|bought|list <название товара>`.

    Коды: 0 — ок, 1 — ошибка (таблица недоступна, товар не найден),
    2 — неверные аргументы. Добавление и удаление озвучиваются «Готово»,
    как в lib.tasks: голосовой цикл сам ничего не говорит.
    """
    from lib.tts import TextToSpeech

    args = list(argv if argv is not None else sys.argv[1:])
    action = args[0] if args else ""
    if action not in ("add", "bought", "list"):
        print('usage: python -m lib.shopping add|bought|list "товар"')
        return 2
    phrase = " ".join(args[1:])
    try:
        handler = ShoppingHandler()
        if action == "add":
            result = handler.add_item(phrase)
        elif action == "bought":
            result = handler.buy_item(phrase)
        else:
            result = handler.list_items()
        _report(result)
        if not result.get("ok"):
            return 1
        if action != "list" and not result.get("duplicate"):
            try:
                TextToSpeech().speak_and_play("Готово")
            except Exception as e:
                print("[Voice] Озвучка не удалась:", e)
        return 0
    except Exception as e:
        print(f"error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
