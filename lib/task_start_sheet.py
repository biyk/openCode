"""Клиент Google Таблицы «real_life_tasks» для запуска задач.

Пишем ровно туда же, в каком формате и по тем же колонкам, что пишет
JS-клиент приложения (см. doit.md): значения — plain ASCII строки,
при старте меняется ТОЛЬКО ячейка G (start_date) найденной строки.
Sheet ↔ Calendar связывает task_uuid (колонка D).
"""

from typing import Any, Optional

from lib.google_calendar import GoogleCalendar

# Актуальная таблица JS-приложения (в doit.md фигурирует устаревший дефолт
# 1-EZE8…, где листов real_life_* уже нет).
SPREADSHEET_ID = "1QPyPVOGKX5FWQUlB91q7hNNr3V7AWGho54RH5m_YMrY"
SHEET_NAME = "real_life_tasks"
UUID_COL = "D"      # task_uuid — стабильный ключ строки
START_COL = "G"     # start_date: '' / '0' → не запущена, unix-мс → идёт
FINISH_COL = "O"    # task_finish_date: накопленная длительность до паузы


def parse_ms_cell(value: Any) -> int:
    """Целое из ячейки-мс: ''/мусор/NBSP/float-текст → 0, без исключений."""
    text = str(value if value is not None else "").strip().replace("\u00a0", "")
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


class TaskStartSheet:
    """Чтение/точечная запись real_life_tasks поверх OAuth token.json."""

    def __init__(self, calendar: Optional[GoogleCalendar] = None,
                 spreadsheet_id: str = SPREADSHEET_ID) -> None:
        self._gcal = calendar or GoogleCalendar()
        self._spreadsheet_id = spreadsheet_id
        self._service: Any = None

    def _ensure_service(self) -> Any:
        """Лениво строит Sheets API на тех же creds, что и календарь."""
        if self._service is None:
            import googleapiclient.discovery
            creds = self._gcal._load_or_get_credentials()
            self._service = googleapiclient.discovery.build(
                "sheets", "v4", credentials=creds)
        return self._service

    def find_row_by_uuid(self, task_uuid: str) -> Optional[int]:
        """1-based номер строки листа по task_uuid (колонка D) или None."""
        resp = self._ensure_service().spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_NAME}!{UUID_COL}2:{UUID_COL}").execute()
        for offset, row in enumerate(resp.get("values") or []):
            if row and str(row[0]).strip() == task_uuid:
                return offset + 2   # +2: сдвиг от D2 и строка-заголовок
        return None

    def read_start_finish(self, row_idx: int) -> tuple[int, int]:
        """(start_date, task_finish_date) одной batch-чтением (без расов)."""
        ranges = [f"{SHEET_NAME}!{c}{row_idx}"
                  for c in (START_COL, FINISH_COL)]
        resp = self._ensure_service().spreadsheets().values().batchGet(
            spreadsheetId=self._spreadsheet_id, ranges=ranges).execute()
        cells = [r.get("values") or [[]] for r in resp.get("valueRanges") or []]
        return (parse_ms_cell(cells[0][0][0] if cells[0] else ""),
                parse_ms_cell(cells[1][0][0] if len(cells) > 1 and cells[1]
                              else ""))

    def write_start(self, row_idx: int, start_ms: int) -> None:
        """Точечная запись единственной ячейки G<row> (формат JS: str(int))."""
        self._ensure_service().spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_NAME}!{START_COL}{row_idx}",
            valueInputOption="RAW",
            body={"values": [[str(int(start_ms))]]}).execute()
