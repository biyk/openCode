# TOOLTIP: Листы наград и журнала списаний (real_life_rewards, rewards_history)
"""Чтение каталога наград и запись списаний hero_money в журнал.

Листы той же таблицы real_life_* (см. real_life_sheet), но живут они своей
жизнью: покупка награды — это строка в rewards_history и минус на hero_money.
Порядок колонок журнала повторяет JS-клиент:

    item_id | claim_date | gold_spent | reward_title | reward_id | <дата>

где claim_date — epoch мс, а последняя колонка — даточисловый серийный номер
Google (дни с 1899-12-30); шапки у неё нет, но клиент её пишет.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from lib.taskflow.real_life_sheet import RealLifeSheet
from lib.taskflow.cells import as_float

SHEET_REWARDS = "real_life_rewards"
SHEET_HISTORY = "rewards_history"
HERO_EPOCH_DAYS = 25569.0        # серий дат Google vs epoch Unix
MS_PER_DAY = 86400000.0


class RewardsSheet(RealLifeSheet):
    """Каталог наград (только чтение) и журнал списаний (append)."""

    def find_reward(self, title: str) -> Optional[dict[str, Any]]:
        """Награда из real_life_rewards по заголовку (без регистра/пробелов).

        Возвращает {title, cost, reward_id} — заголовок отдаём как в таблице
        (там висят хвостовые пробелы, их пишет и JS-клиент).
        """
        wanted = " ".join(str(title or "").casefold().split())
        for row in self._get(f"{SHEET_REWARDS}!A1:C")[1:]:
            if not row or len(row) < 3:
                continue
            if " ".join(str(row[0] or "").casefold().split()) != wanted:
                continue
            return {"title": str(row[0]), "reward_id": str(row[2]).strip(),
                    "cost": as_float(row[1] if len(row) > 1 else 0)}
        return None

    def append_claim(self, reward: dict[str, Any], amount: int,
                     now: datetime) -> str:
        """Одна строка покупки в rewards_history (колонки A:F); id строки."""
        item_id = str(uuid4())
        claim_ms = int(now.timestamp() * 1000)
        self._ensure_service().spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=f"{SHEET_HISTORY}!A:F",
            valueInputOption="RAW",
            body={"values": [[item_id, claim_ms, amount,
                              reward["title"], reward["reward_id"],
                              claim_ms / MS_PER_DAY + HERO_EPOCH_DAYS]]}).execute()
        return item_id

    def spend(self, reward: dict[str, Any], amount: int,
              now: datetime) -> str:
        """hero_money −= amount и строка журнала; id строки (для аудита)."""
        self.add_hero_money(-float(amount))
        return self.append_claim(reward, amount, now)
