"""Разбор значений ячеек real_life_* в числа.

Листы приложения пишут и JS-клиент, и голосовые команды, поэтому в одной
колонке встречаются число и текст, а локаль ru добавляет запятую вместо
точки и неразрывные пробелы в разрядах. Разбираем всё это молча: пустая
или мусорная ячейка — это default, а не исключение.
"""

from typing import Any


def _clean(value: Any) -> str:
    """Ячейка → текст для разбора числа: NBSP, пробелы, запятая-десятичная."""
    text = str(value if value is not None else "")
    return text.replace("\u00a0", "").replace(" ", "").replace(",", ".").strip()


def as_int(value: Any, default: int = 0) -> int:
    """Целое из ячейки; ''/мусор → default, без исключений."""
    try:
        return int(float(_clean(value) or "0"))
    except ValueError:
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    """Вещественное из ячейки; ''/мусор → default, без исключений."""
    try:
        return float(_clean(value) or "0")
    except ValueError:
        return default
