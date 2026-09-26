"""Поиск дубликата задачи перед добавлением: строгое совпадение → Laya.

Строгое совпадение нормализованных названий отсекается без модели.
Если строгого нет — Laya вопросом-выбором проверяет, не сводится ли
новая задача к одной из существующих; список режем на пачки под лимит
вариантов сервера (laya.max_opts). Кандидат из пачки принимается любым
(любой выбор не none), но решение даёт только подтверждающий парный
вопрос: он надёжнее, чем аргмакс большой пачки. Laya недоступна или
не подтвердила дубликат — задача считается новой (добавление не
блокируется).
"""

from typing import Callable, Optional

from lib.taskflow.tasks_parse import _normalize

# Порог подтверждающего парного вопроса: дубликатом считается только
# уверенный ответ Laya (c >= 0.9). Ниже — считаем задачу новой:
# калибровка показала, что при низких c модель лепит дубли на
# несвязанные пары («провести химические опыты» vs «Выбить квартплату
# через суд» пришло с c=0.22).
DUP_THRESHOLD = 0.9
# Вопрос по пачке — только кандидат: годится любой выбор не none
# (уверенность на 15 вариантах шумная, ~0.02-0.9).
BATCH_THRESHOLD = 0.0
# Лимит laya.max_opts: сервер принимает не больше 16 вариантов в вопросе.
MAX_OPTS = 16
# Названий на вопрос: остальные варианты занимает none (добавляет detect()).
BATCH_OPTS = MAX_OPTS - 1
# Не спрашиваем модель о десятках задач за раз.
MAX_EXISTING = 40
NONE_DESCRIPTION = "новой задачи нет в списке — она уникальна"
DUP_INSTRUCTIONS = (
    "Выбери открытую задачу из списка, которую повторяет новая задача "
    "(то же действие). Если не повторяет — none: " + NONE_DESCRIPTION + "."
)
PAIR_INSTRUCTIONS = (
    "Новая задача повторяет открытую задачу (то же действие)? Если "
    "повторяет — выбери её, если это разные задачи — none."
)
PAIR_NONE = "это разные задачи"


def find_duplicate(title: str, existing: list[dict],
                   get_decision: Optional[Callable[[], object]] = None,
                   report: Optional[Callable[[str], None]] = None,
                   ) -> Optional[dict]:
    """Ищет дубликат среди existing: exact, затем вопрос Laya.

    Возвращает {"id", "title", "method"} (method: exact|laya) или None;
    для laya добавляет "score" — уверенность модели (для отладки порога).
    get_decision — фабрика LayaDecision (вызывается лениво, только
    когда exact не нашёлся и есть варианты); None — Laya не спрашиваем.
    report — колбэк трассировки поиска: что ищем и какой вердикт Laya
    вынесла по пачке (c, t).
    """
    def say(msg: str) -> None:
        if report is not None:
            report(msg)

    none_seen = {"heard": False, "c": 0.0}

    def note_verdict(choice: str, confidence: float) -> None:
        if choice == "none":
            none_seen["heard"] = True
            none_seen["c"] = confidence

    query = _normalize(title)
    if not query:
        return None
    for task in existing:
        if _normalize(str(task.get("title", ""))) == query:
            return _hit(task, "exact")
    options = [t for t in existing if t.get("title")][:MAX_EXISTING]
    if not options or get_decision is None:
        return None
    decision = get_decision()
    if decision is None:
        say("laya недоступна — ищем только строгим совпадением")
        return None
    say(f"ищу «{title}» среди {len(options)} открытых задач")
    for start in range(0, len(options), BATCH_OPTS):
        batch = options[start:start + BATCH_OPTS]
        num = start // BATCH_OPTS + 1
        none_seen["heard"] = False
        task, verdict = _ask_laya(decision, title, batch, note_verdict)
        if task is None:
            if none_seen["heard"]:
                say(f"пачка {num}: кандидата нет — Laya: «none» "
                    f"(c={none_seen['c']:.2f})")
            else:
                say(f"пачка {num}: кандидата нет (Laya без вердикта)")
            continue
        say(f"пачка {num}: кандидат «{task['title']}» "
            f"(c={verdict[1]:.2f} t={verdict[2]:.3f})")
        conf = _confirm(decision, title, task)
        if conf is None:
            say("подтверждение: модель ответила «разные задачи»")
            continue
        if conf >= DUP_THRESHOLD:
            say(f"подтверждение: c={conf:.4f} >= {DUP_THRESHOLD} — дубликат")
            return _hit(task, "laya", conf)
        say(f"подтверждение: c={conf:.4f} < {DUP_THRESHOLD} — не дубликат")
    return None


def _ask_laya(decision, title: str, batch: list[dict],
              on_verdict: Optional[Callable[[str, float], None]] = None
              ) -> tuple:
    """Один вопрос-выбор по пачке: (кандидат, вердикт Laya) — оба могут быть None.

    Критерии — сами названия (значение — описание «открытая задача: …»):
    на такие ключи Laya отвечает надёжнее, чем на индексы t0..tN.
    Вердикт (choice, c, t) возвращаем и когда кандидата нет — для трассы.
    """
    criteria = {str(t["title"]): f"открытая задача: {t['title']}"
                for t in batch}
    criteria["none"] = NONE_DESCRIPTION
    verdict = decision.detect(
        f"Новая задача: {title}", criteria=criteria,
        instructions=DUP_INSTRUCTIONS, threshold=BATCH_THRESHOLD,
        on_verdict=on_verdict)
    return _pick(batch, verdict), verdict


def _confirm(decision, title: str, task: dict) -> Optional[float]:
    """Парный вопрос; возвращает уверенность ответа про кандидата.

    Порог DUP_THRESHOLD применяет вызывающий (нужен сам c и при
    отказе); None — модель выбрала none или ответила не про кандидата.
    """
    name = str(task["title"])
    verdict = decision.detect(
        f"Новая задача: {title}",
        criteria={name: f"открытая задача: {name}", "none": PAIR_NONE},
        instructions=PAIR_INSTRUCTIONS, threshold=0.0)
    if verdict and verdict[0] == name:
        return float(verdict[1])
    return None


def _pick(batch: list[dict], verdict: Optional[tuple]) -> Optional[dict]:
    """Выбор Laya (название задачи) → запись из batch; None мимо."""
    if verdict is None:
        return None
    for task in batch:
        if str(task["title"]) == verdict[0]:
            return task
    return None


def _hit(task: dict, method: str, score: Optional[float] = None) -> dict:
    """Запись отчёта о найденном дубликате (score — c Laya)."""
    hit = {"id": str(task.get("id", "")),
           "title": str(task.get("title", "")), "method": method}
    if score is not None:
        hit["score"] = round(score, 4)
    return hit
