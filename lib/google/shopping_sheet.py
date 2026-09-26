"""Клиент листа «Список покупок» в Google Таблице.

Транспорт — тот же OAuth-токен, что у календаря (scope spreadsheets),
сервис строится лениво. Таблица плоская: колонка A — товар, колонка B —
дата добавления, строка 1 — шапка. «купил X» удаляет строку целиком
(batchUpdate deleteDimension), чтобы список не покрывался дырами.

Читаем UNFORMATTED_VALUE, пишем RAW: значения остаются тем же текстом,
локаль ru не пересобирает дату в число.
"""

import re
from typing import Any, Optional

from lib.google_calendar import GoogleCalendar

SPREADSHEET_ID = "1GPiQPzUWRZ0G23OlSCTIVt266TZh_AcGM1B0F7W71jo"
SHEET_NAME = "Лист1"
SHEET_ID = 0                       # gid листа из URL таблицы
HEADER = ("Товар", "Добавлено")
FIRST_DATA_ROW = 2                 # строка 1 — шапка

_ROW_RE = re.compile(r"![A-Z]+(\d+)")


def _row_from_range(rng: Optional[str]) -> Optional[int]:
    """Номер строки из updatedRange («Лист1!A7:B7» → 7), иначе None."""
    match = _ROW_RE.search(rng or "")
    return int(match.group(1)) if match else None


def _quoted(name: str) -> str:
    """Имя листа для A1-нотации: кавычки нужны, если внутри есть пробел."""
    return f"'{name}'" if " " in name else name


class ShoppingSheet:
    """Чтение и точечная запись одного листа-списка покупок."""

    def __init__(self, calendar: Optional[GoogleCalendar] = None,
                 spreadsheet_id: str = SPREADSHEET_ID,
                 sheet_name: str = SHEET_NAME,
                 sheet_id: int = SHEET_ID) -> None:
        self._gcal = calendar or GoogleCalendar()
        self._spreadsheet_id = spreadsheet_id
        self._sheet = _quoted(sheet_name)
        self._sheet_id = sheet_id
        self._service: Any = None

    def _rng(self, tail: str) -> str:
        """Диапазон внутри листа («A2:B» → «Лист1!A2:B»)."""
        return f"{self._sheet}!{tail}"

    def _ensure_service(self) -> Any:
        """Лениво строит Sheets API на creds календаря (см. task_start_sheet)."""
        if self._service is None:
            import googleapiclient.discovery
            creds = self._gcal._load_or_get_credentials()
            self._service = googleapiclient.discovery.build(
                "sheets", "v4", credentials=creds)
        return self._service

    # ---------- Чтение ----------

    def rows(self) -> list[list[Any]]:
        """Строки A:B ниже шапки КАК В ЛИСТЕ (пустые тоже) — ради номеров."""
        resp = self._ensure_service().spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range=self._rng(f"A{FIRST_DATA_ROW}:B"),
            valueRenderOption="UNFORMATTED_VALUE").execute()
        return resp.get("values") or []

    def items(self) -> list[dict]:
        """[{"row": номер в листе, "name": товар}] — пустые строки пропуск."""
        out: list[dict] = []
        for idx, row in enumerate(self.rows(), start=FIRST_DATA_ROW):
            if row and str(row[0]).strip():
                out.append({"row": idx, "name": str(row[0]).strip()})
        return out

    # ---------- Запись ----------

    def ensure_header(self) -> None:
        """Пишет шапку A1:B1, если лист пуст (иначе первая строка — товар)."""
        resp = self._ensure_service().spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range=self._rng("A1:B1")).execute()
        first = (resp.get("values") or [[]])[0]
        if first and str(first[0]).strip():
            return
        self._ensure_service().spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=self._rng("A1:B1"), valueInputOption="RAW",
            body={"values": [list(HEADER)]}).execute()

    def append_item(self, name: str, stamp: str) -> Optional[int]:
        """Одна строка A:B в конец списка; возвращает номер новой строки."""
        resp = self._ensure_service().spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id, range=self._rng("A:B"),
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [[name, stamp]]}).execute()
        return _row_from_range((resp.get("updates") or {})
                               .get("updatedRange"))

    def delete_row(self, row_idx: int) -> None:
        """Удаляет строку с A1-номером row_idx (остальные сдвигаются вверх).

        Индексы deleteDimension — 0-based (номера строк сетки), а не
        A1-номера: для строки 2 это [1, 2). Ошибка на единицу молча
        сдвигает удаление на строку вниз (проверено на живой таблице).
        """
        self._ensure_service().spreadsheets().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"requests": [{"deleteDimension": {"range": {
                "sheetId": self._sheet_id,
                "dimension": "ROWS",
                "startIndex": row_idx - 1,
                "endIndex": row_idx,
            }}}]}).execute()
