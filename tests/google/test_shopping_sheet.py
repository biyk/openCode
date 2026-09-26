"""Юнит-тесты транспорта листа «Список покупок» (lib/google/shopping_sheet.py).

Google-сервис подменяем заглушкой: проверяем диапазоны внутри листа,
RAW при записи и UNFORMATTED_VALUE при чтении, шапку только на пустом
листе и что удаление позиции — это deleteDimension, а не очистка ячеек.
"""

from lib.google.shopping_sheet import HEADER, ShoppingSheet, _row_from_range

DATA_RANGE = "Лист1!A2:B"
HEAD_RANGE = "Лист1!A1:B1"


class _Req:
    def __init__(self, result=None):
        self._result = result

    def execute(self):
        return self._result


class _Values:
    """Заглушка spreadsheets().values(): помнит вызовы, отдаёт заготовки."""

    def __init__(self, gets=None, append_range=None):
        self.gets = gets or {}
        self.append_range = append_range
        self.reads = []
        self.updates = []
        self.appended = []

    def get(self, **kw):
        self.reads.append(kw)
        return _Req({"values": self.gets.get(kw["range"])})

    def update(self, **kw):
        self.updates.append(kw)
        return _Req({})

    def append(self, **kw):
        self.appended.append(kw)
        return _Req({"updates": {"updatedRange": self.append_range}})


class _Sheets:
    def __init__(self, values):
        self._values = values
        self.batch = []

    def values(self):
        return self._values

    def batchUpdate(self, **kw):
        self.batch.append(kw)
        return _Req({})


class _Service:
    def __init__(self, values):
        self._sheets = _Sheets(values)

    def spreadsheets(self):
        return self._sheets


def api(gets=None, append_range=None, **kw):
    """Возвращает (лист, values-заглушку, sheets-заглушку) без OAuth."""
    sheet = ShoppingSheet(calendar=object(), spreadsheet_id="SID", **kw)
    sheet._service = _Service(_Values(gets, append_range))
    sheets = sheet._service.spreadsheets()
    return sheet, sheets.values(), sheets


def test_items_numbers_rows_and_skips_empty():
    """Номера строк — 1-based от строки 2 (шапка не позиция товара)."""
    sheet, values, _ = api({DATA_RANGE: [["Молоко", "26.09.2026"], [""],
                                         ["  Хлеб  ", ""], None]})
    assert sheet.items() == [{"row": 2, "name": "Молоко"},
                             {"row": 4, "name": "Хлеб"}]
    read = values.reads[0]
    assert read["range"] == DATA_RANGE
    assert read["valueRenderOption"] == "UNFORMATTED_VALUE"


def test_ensure_header_writes_only_when_sheet_is_empty():
    """Пустой лист — шапка A1:B1 в RAW; непустой — ни одной записи."""
    sheet, values, _ = api({HEAD_RANGE: [[]], DATA_RANGE: []})
    sheet.ensure_header()
    assert values.updates[0]["range"] == HEAD_RANGE
    assert values.updates[0]["body"]["values"] == [list(HEADER)]

    sheet, values, _ = api({HEAD_RANGE: [list(HEADER)], DATA_RANGE: []})
    sheet.ensure_header()
    assert values.updates == []


def test_append_item_inserts_row_and_reports_its_number():
    """append в A:B (RAW, INSERT_ROWS) + номер строки из updatedRange."""
    sheet, values, _ = api(append_range="Лист1!A7:B7")
    assert sheet.append_item("Молоко", "26.09.2026 13:45") == 7
    sent = values.appended[0]
    assert sent["range"] == "Лист1!A:B"
    assert sent["valueInputOption"] == "RAW"
    assert sent["insertDataOption"] == "INSERT_ROWS"
    assert sent["body"]["values"] == [["Молоко", "26.09.2026 13:45"]]


def test_delete_row_uses_delete_dimension():
    """Удаление — batchUpdate deleteDimension (лист сдвигается вверх).

    Индексы API 0-based: строка 4 листа — это [3, 4).
    """
    sheet, _, sheets = api()
    sheet.delete_row(4)
    sent = sheets.batch[0]
    assert sent["spreadsheetId"] == "SID"
    request = sent["body"]["requests"][0]["deleteDimension"]["range"]
    assert request == {"sheetId": 0, "dimension": "ROWS",
                       "startIndex": 3, "endIndex": 4}


def test_sheet_name_with_space_is_quoted_in_ranges():
    """Имя листа с пробелом берётся в кавычки — иначе A1-нотация ломается."""
    sheet, values, _ = api({}, sheet_name="Мой лист")
    sheet.rows()
    assert values.reads[0]["range"] == "'Мой лист'!A2:B"
    assert sheet._sheet_id == 0

    sheet, _, sheets = api({}, sheet_id=5)
    sheet.delete_row(2)
    rng = sheets.batch[0]["body"]["requests"][0]["deleteDimension"]["range"]
    assert rng["sheetId"] == 5
    assert (rng["startIndex"], rng["endIndex"]) == (1, 2)


def test_row_from_range_tolerates_missing_response():
    """Нет updatedRange (или имя листа с кавычками) — номер или None."""
    assert _row_from_range("'Мой лист'!A12:B12") == 12
    assert _row_from_range(None) is None
    assert _row_from_range("без строки") is None
    assert _row_from_range("Лист1!A:B") is None
