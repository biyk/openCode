"""Клиент листов real_life_* для засчёта выполнения (эквивалент ✅, done.md).

Транспорт поверх того же OAuth-токена, что и календарь: строка задачи A:T
по task_uuid, событие-«галочка» colorId=7, журнал task_executions и
hero_money. Формулы и порядок операций — в lib/taskflow/done_task.py.

Читаем UNFORMATTED_VALUE, чтобы не трогать типы ячеек: в таблице лежат и
числа, и текст («0000000», uuid). Обновляемые колонки пишем числами —
локаль ru сама отобразит их с запятой, а JS-клиент читает Number(...).
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from lib.google_calendar import GoogleCalendar
from lib.taskflow.cells import as_float
from lib.taskflow.task_start_sheet import SHEET_NAME, SPREADSHEET_ID

SHEET_TASKS = SHEET_NAME                      # real_life_tasks
SHEET_EXECUTIONS = "task_executions"
SHEET_HERO = "real_life_hero"
UUID_COL = 3                                  # колонка D — task_uuid
ROW_WIDTH = 20                                # колонки A:T
HERO_MONEY_CODE = "hero_money"

# Порядок колонок real_life_tasks (совпадает с JS-приложением).
COLS = {
    "task_title": 0, "task_time": 1, "task_description": 2,
    "task_uuid": 3, "task_sort": 4, "task_color": 5, "start_date": 6,
    "task_date": 7, "repeat_index": 8, "repeat_days_of_week": 9,
    "repeat_mode": 10, "date_mode": 11, "money_reward": 12,
    "break_multiplier": 13, "task_finish_date": 14,
    "number_of_executions": 15, "excludes": 16, "task_before": 17,
    "task_after": 18, "last_execution": 19,
}


def _pad(row: list[Any]) -> list[Any]:
    """Ровно ROW_WIDTH значений: недостающие хвосты — пустые строки."""
    return (list(row) + [""] * ROW_WIDTH)[:ROW_WIDTH]


class RealLifeSheet:
    """Только ввод/вывод листов приложения и события-галочки."""

    def __init__(self, calendar: Optional[GoogleCalendar] = None,
                 spreadsheet_id: str = SPREADSHEET_ID) -> None:
        self._gcal = calendar or GoogleCalendar()
        self._spreadsheet_id = spreadsheet_id
        self._service: Any = None

    def _ensure_service(self) -> Any:
        """Лениво строит Sheets API на creds календаря (см. task_start_sheet)."""
        if self._service is None:
            import googleapiclient.discovery
            creds = self._gcal._load_or_get_credentials()
            self._service = googleapiclient.discovery.build(
                "sheets", "v4", credentials=creds)
        return self._service

    def _get(self, rng: str) -> list[list[Any]]:
        """Чтение диапазона без форматирования (типы ячеек как в таблице)."""
        resp = self._ensure_service().spreadsheets().values().get(
            spreadsheetId=self._spreadsheet_id, range=rng,
            valueRenderOption="UNFORMATTED_VALUE").execute()
        return resp.get("values") or []

    # ---------- real_life_tasks ----------

    def find_task_row(self, task_uuid: str) -> Optional[tuple[int, list[Any]]]:
        """(1-based номер строки, значения A:T) задачи; None — если её нет."""
        for offset, row in enumerate(self._get(f"{SHEET_TASKS}!A1:T")[1:],
                                     start=2):
            values = _pad(row)
            if str(values[UUID_COL]).strip() == task_uuid:
                return offset, values
        return None

    def write_task_row(self, row_idx: int, values: list[Any]) -> None:
        """Один RAW-update строки A:T (колонку B вызывающий не меняет)."""
        self._ensure_service().spreadsheets().values().update(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_TASKS}!A{row_idx}:T{row_idx}",
            valueInputOption="RAW",
            body={"values": [_pad(values)]}).execute()

    # ---------- событие-«галочка» ----------

    def find_done_event(self, task_uuid: str, now: datetime) -> Optional[dict]:
        """Сегодняшнее событие с task_uuid в описании (или None)."""
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = self._gcal.list_events_between(
            day_start, day_start + timedelta(days=1))
        for ev in events:
            if task_uuid in (ev.get("description") or ""):
                return ev
        return None

    def upsert_done_event(self, summary: str, task_uuid: str, minutes: int,
                          end: datetime,
                          event_id: Optional[str] = None) -> bool:
        """Галочка colorId=7. True — создана заново, False — обновлена.

        RuntimeError — запрос к календарю не прошёл (счётчики строки тогда
        не сдвигаются: вызывающий прерывает засчёт до записи таблицы).
        """
        event_id_old = event_id
        done = self._gcal.put_done_event(
            summary=summary, description=task_uuid, minutes=minutes,
            end=end, event_id=event_id)
        if not done:
            raise RuntimeError("событие-галочка в календаре не создано")
        return event_id_old is None

    # ---------- журнал и герой ----------

    def execution_rows(self) -> list[list[Any]]:
        """task_executions целиком (шапка + строки) — для дисциплины."""
        return self._get(f"{SHEET_EXECUTIONS}!A1:G")

    def append_execution(self, cells: list[Any]) -> None:
        """Одна строка журнала (порядок A..G, как пишет JS-клиент)."""
        self._ensure_service().spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_EXECUTIONS}!A:G",
            valueInputOption="RAW",
            body={"values": [cells]}).execute()

    def add_hero_money(self, delta: float) -> None:
        """hero_money += delta; нет строки — добавляем её, как JS."""
        rows = self._get(f"{SHEET_HERO}!A1:B")
        for idx, row in enumerate(rows[1:], start=2):
            if row and str(row[0]).strip() == HERO_MONEY_CODE:
                old = as_float(row[1] if len(row) > 1 else 0)
                self._ensure_service().spreadsheets().values().update(
                    spreadsheetId=self._spreadsheet_id,
                    range=f"{SHEET_HERO}!B{idx}", valueInputOption="RAW",
                    body={"values": [[old + delta]]}).execute()
                return
        self._ensure_service().spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_HERO}!A:B", valueInputOption="RAW",
            body={"values": [[HERO_MONEY_CODE, delta]]}).execute()
