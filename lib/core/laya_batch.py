"""Транспорт choice-вопроса Laya + разбиение наборов критериев под max_opts.

Сервер Laya (`laya.max_opts = 16`) отклоняет вопрос, где вариантов больше
лимита, ошибкой 422 — а `detect()` глотал её молча и возвращал None, из-за
чего слой распознавания команд отваливался целиком (16 команд + `none` = 17).
Здесь: разовый POST /v1/systemone (`run_query`, ошибки не глотает — их
пишет вызывающий), разбор критериев на примерно равные батчи (`plan_batches`,
каждый ≤ лимита) и двухступенчатый выбор (`query_batches`): победитель в
каждом батче, затем финальный вопрос «кто лучший среди победителей».
"""

import json
import math
import time
import urllib.request

from lib.core.tuning import LAYA_MAX_OPTS

# laya.max_opts: сервер не принимает больше вариантов в одном вопросе
# (значение — в lib.core.tuning, единая ручка на весь проект).
MAX_OPTS = LAYA_MAX_OPTS
# Вариантов команды на батч: один слот держим под `none` (добавляет клиент).
BATCH_OPTS = MAX_OPTS - 1


def run_query(url, timeout, default_instructions, text, crit,
              instructions=None, limit=0.0, on_verdict=None):
    """Один POST /v1/systemone: (choice, confidence, elapsed) либо None.

    None — мимо (нет выбора / `none` / вне crit) или ниже порога `limit`.
    on_verdict(choice, c) зовётся вердиктом до отбрасывания (виден и `none`).
    Сетевые ошибки НЕ глотает — их логирует вызывающий (`detect`).
    """
    payload = {"state": {"body": text}, "questions": {"command": {
        "type": "choice",
        "instructions": instructions or default_instructions,
        "criteria": crit,
    }}}
    t0 = time.perf_counter()
    req = urllib.request.Request(
        url + "/v1/systemone",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    answer = ((body or {}).get("answers", {}) or {}).get("command", {}) or {}
    choice = answer.get("choice")
    confidence = float(answer.get("confidence", 0.0))
    if on_verdict is not None and choice is not None:
        on_verdict(str(choice), confidence)
    if choice is None or choice == "none" or choice not in crit:
        return None
    if confidence < limit:
        return None
    return choice, confidence, time.perf_counter() - t0


def plan_batches(keys, capacity=BATCH_OPTS):
    """Ключи критериев (без none) на батчи <= capacity примерно равного размера.

    16 ключей при capacity 15 → два батча по 8 (не 15+1): равные батчи
    держат уверенность сопоставимой между вопросами.
    """
    keys = list(keys)
    if capacity < 1 or len(keys) <= capacity:
        return [keys] if keys else []
    size = math.ceil(len(keys) / math.ceil(len(keys) / capacity))
    return [keys[i:i + size] for i in range(0, len(keys), size)]


def query_batches(crit, single, final=None):
    """Выбор по всем критериям: батчи + финальное сравнение победителей.

    crit — полные критерии (со `none`); single(sub_crit) делает один
    choice-запрос по батчу и возвращает (choice, confidence, elapsed)
    либо None. Один батч (len ≤ MAX_OPTS) — как раньше. Иначе из каждого
    батча берётся победитель, а среди победителей решает финальный вопрос
    final(sub_crit) (тот же формат): уверенность разных батчей
    некалибрована и сравнивать её напрямую нельзя («аргмакс по куче
    вопросов»), а прямой вопрос «кто из них лучше» надёжен — тот же
    принцип, что и парное подтверждение в tasks_dedup. Финал решает:
    none/ниже порога — команды нет. Один победитель — финал не нужен
    (сравнивать не с чем), final=None — старый аргмакс по уверенности.
    elapsed — сумма по всем запросам (батчи + финал).
    """
    if len(crit) <= MAX_OPTS:
        return single(crit)
    none_desc = crit.get("none", "")
    winners = []
    total = 0.0
    for grp in plan_batches([k for k in crit if k != "none"]):
        sub = {k: crit[k] for k in grp}
        sub["none"] = none_desc
        res = single(sub)
        if res is None:
            continue
        total += res[2]
        winners.append(res)
    if not winners:
        return None
    best = max(winners, key=lambda r: r[1])
    if final is None or len(winners) < 2:
        return best[0], best[1], total
    finals = {w[0]: crit[w[0]] for w in winners}
    finals["none"] = none_desc
    res = final(finals)
    if res is None:
        return None
    total += res[2]
    return res[0], res[1], total
