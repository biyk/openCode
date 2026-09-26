"""Тесты голосовых команд списка покупок (lib/shopping.py).

Таблица подменяется заглушкой: проверяем, что «нужно купить X» пишет
строку (товар + дата), «купил X» удаляет найденную строку, дубликат
блокирует добавление ТОЛЬКО при включённом dedup, и что коды возврата
CLI соответствуют смыслу операции.
"""

from datetime import datetime

from lib.shopping import ShoppingHandler, clean_item, main

NEVER = {"dedup": {"enabled": False, "fuzzy": False, "threshold": 0.9}}
EXACT = {"dedup": {"enabled": True, "fuzzy": False, "threshold": 0.9}}


class FakeTts:
    """Заглушка TTS: пишет озвученные фразы в список вызывающего."""

    def __init__(self, sink):
        self._sink = sink

    def speak_and_play(self, text, **kw):
        self._sink.append(text)


class FakeSheet:
    """Заглушка ShoppingSheet: список в памяти, все вызовы записываем."""

    def __init__(self, items=None):
        self.rows = list(items or [])     # [{"row", "name"}]
        self.appended = []
        self.deleted = []
        self.header_written = 0

    def items(self):
        return [dict(row) for row in self.rows]

    def ensure_header(self):
        self.header_written += 1

    def append_item(self, name, stamp):
        self.appended.append((name, stamp))
        row = 2 + len(self.rows) + len(self.appended) - 1
        self.rows.append({"row": row, "name": name})
        return row

    def delete_row(self, row_idx):
        self.deleted.append(row_idx)
        self.rows = [r for r in self.rows if r["row"] != row_idx]


def handler(items=None, config=None, now=None):
    sheet = FakeSheet(items)
    return ShoppingHandler(sheet=sheet, config=config or NEVER,
                           now=now or datetime(2026, 9, 26, 13, 45)), sheet


def test_clean_item_collapses_spaces_and_trailing_punctuation():
    """« молоко .» → «молоко»: хвостовая пунктуация распознавателя режется."""
    assert clean_item("  молоко. ") == "молоко"
    assert clean_item("сыр   косичка!?") == "сыр косичка"
    assert clean_item("") == ""


def test_add_writes_item_and_stamp():
    """«нужно купить X»: шапка + строка с датой в формате dd.mm.YYYY HH:MM."""
    h, sheet = handler(now=datetime(2026, 9, 26, 13, 5))
    result = h.add_item(" молоко ")
    assert result == {"ok": True, "action": "add", "item": "молоко",
                      "row": 2}
    assert sheet.header_written == 1
    assert sheet.appended == [("молоко", "26.09.2026 13:05")]


def test_add_does_not_block_duplicates_while_dedup_is_off():
    """Выключенный dedup (нынешний конфиг) — одна и та же позиция дважды."""
    h, sheet = handler([{"row": 2, "name": "Молоко"}], NEVER)
    assert h.add_item("молоко")["ok"] is True
    assert sheet.appended == [("молоко", "26.09.2026 13:45")]


def test_add_skips_when_dedup_is_enabled():
    """Включённый dedup: дубликат не пишется, но ошибка не возвращается."""
    h, sheet = handler([{"row": 2, "name": "МОЛОКО 2л"}], EXACT)
    result = h.add_item("молоко 2л")
    assert result["duplicate"] is True and result["row"] == 2
    assert result["method"] == "exact"
    assert sheet.appended == []


def test_add_empty_name_is_error_without_writes():
    h, sheet = handler()
    result = h.add_item(".")
    assert result["ok"] is False and result["action"] == "add"
    assert sheet.appended == [] and sheet.header_written == 0


def test_buy_deletes_matched_row_by_substring():
    """«купил молоко» убирает строку «Молоко 2л» (поиск по подстроке)."""
    h, sheet = handler([{"row": 2, "name": "Молоко 2л"},
                        {"row": 3, "name": "Хлеб"}])
    result = h.buy_item("молоко")
    assert result == {"ok": True, "action": "buy", "item": "Молоко 2л",
                      "row": 2, "method": "contains"}
    assert sheet.deleted == [2]


def test_buy_unknown_item_reports_error_and_deletes_nothing():
    h, sheet = handler([{"row": 2, "name": "Хлеб"}])
    result = h.buy_item("кефир")
    assert result["ok"] is False and "не найдено" in result["error"]
    assert sheet.deleted == []


def test_list_items_returns_names():
    h, _ = handler([{"row": 2, "name": "Хлеб"}, {"row": 3, "name": "Молоко"}])
    assert h.list_items()["items"] == ["Хлеб", "Молоко"]


def test_handler_builds_sheet_from_config(monkeypatch):
    """spreadsheet_id / sheet_name / sheet_id из секции shopping."""
    created = {}

    def fake_sheet(**kw):
        created.update(kw)
        return FakeSheet()

    monkeypatch.setattr("lib.shopping.ShoppingSheet", fake_sheet)
    ShoppingHandler(config={"spreadsheet_id": "SID", "sheet_name": "Лист2",
                            "sheet_id": 7, "dedup": {"enabled": False}})
    assert created == {"spreadsheet_id": "SID", "sheet_name": "Лист2",
                       "sheet_id": 7}


def test_handler_without_config_keys_uses_defaults(monkeypatch):
    created = {}
    monkeypatch.setattr("lib.shopping.ShoppingSheet",
                        lambda **kw: created.update(kw) or FakeSheet())
    ShoppingHandler(config={})
    assert created["spreadsheet_id"].startswith("1GPiQP")
    assert created["sheet_name"] == "Лист1" and created["sheet_id"] == 0


def test_load_shopping_config_swallows_errors(monkeypatch):
    """Битый commands.json — пустой конфиг (работаем на дефолтах таблицы)."""
    import lib.shopping as shopping

    monkeypatch.setattr(shopping, "get_device_commands_path",
                        lambda host: (_ for _ in ()).throw(OSError("нет")))
    assert shopping.load_shopping_config() == {}


def test_cli_add_and_buy_exit_codes(monkeypatch, capsys):
    """CLI: 0 — операция прошла, 1 — товар не найден, 2 — нет действия."""
    calls = []
    monkeypatch.setattr("lib.tts.TextToSpeech",
                        lambda *a, **kw: FakeTts(calls))
    h, _ = handler([{"row": 2, "name": "Молоко"}])
    monkeypatch.setattr("lib.shopping.ShoppingHandler", lambda: h)

    assert main(["add", "сыр"]) == 0
    assert main(["bought", "молоко"]) == 0
    assert main(["bought", "кефир"]) == 1
    assert main(["промыть"]) == 2
    out = capsys.readouterr().out
    assert "item: сыр" in out and "reason:" in out
    assert calls == ["Готово", "Готово"]   # озвучка только на успех операции


def test_cli_list_does_not_speak(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("lib.tts.TextToSpeech",
                        lambda *a, **kw: FakeTts(calls))
    h, _ = handler([{"row": 2, "name": "Молоко"}])
    monkeypatch.setattr("lib.shopping.ShoppingHandler", lambda: h)
    assert main(["list"]) == 0
    assert "items: Молоко" in capsys.readouterr().out
    assert calls == []


def test_cli_reports_exception_as_error_code(monkeypatch):
    """Сбой таблицы/OAuth — не падение процесса, а код 1 и текст ошибки."""
    def boom():
        raise RuntimeError("нет доступа к таблице")

    monkeypatch.setattr("lib.shopping.ShoppingHandler", boom)
    assert main(["add", "сыр"]) == 1
