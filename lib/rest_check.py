"""Опрос модели «отдых ли это окно?»: вопрос, разбор ответа и classify.

Разведено по ролям:
  - ``rest_prompt``   — только строит вопрос модели (structured-формат);
  - ``parse_rest_answer`` — только разбирает ответ («Ответ/Вероятность/Объяснение»);
  - ``classify``      — то и вместе: спрашивает OmniRouter (модель auto) про
    заголовок окна и возвращает разобранный ``RestAnswer``.

Брать заголовок активного окна и печатать результат — дело вызывающего кода
(например ``lib.core.task_monitor``); здесь только работа с моделью.
"""

import re
import time
from typing import NamedTuple, Optional

from lib.providers.omni import OmniRouterClient

_ANSWER_RE = re.compile(r"^\s*ответ\s*[:\-–]\s*(.+)", re.IGNORECASE | re.M)
_PROB_RE = re.compile(
    r"^\s*вероятност\w*\s*[:\-–]\s*([0-9]{1,3})\s*%?", re.IGNORECASE | re.M)
_EXPL_RE = re.compile(r"^\s*объяснен\w*\s*[:\-–]\s*(.+)", re.IGNORECASE | re.M)


def rest_prompt(title: str) -> str:
    """Вопрос модели: отдых ли окно; требует три поля ответа."""
    return (
        f"Заголовок активного окна: «{title}».\n"
        "Отнеси это окно к отдыху — развлечение, соцсеть, видео, музыка, "
        "игра, торренты или безделье (не рабочая задача)?\n"
        "Ответь ровно тремя строками:\n"
        "Ответ: да | нет | не знаю\n"
        "Вероятность: <число от 0 до 100>\n"
        "Объяснение: <одна короткая фраза>"
    )


class RestAnswer(NamedTuple):
    """Разобранный ответ модели: вердикт, уверенность и объяснение."""

    answer: str                 # "да" | "нет" | "не знаю" | "" (не разобрано)
    probability: Optional[int]  # 0..100 либо None
    explanation: str
    is_rest: bool               # True только при answer == "да"


def parse_rest_answer(raw: Optional[str]) -> RestAnswer:
    """Разбирает structured-ответ модели в поля «Ответ/Вероятность/Объяснение»."""
    if not raw or not isinstance(raw, str):
        return RestAnswer("", None, "", False)
    answer = _normalize(_grab(_ANSWER_RE, raw))
    prob_m = _PROB_RE.search(raw)
    probability = int(prob_m.group(1)) if prob_m else None
    explanation = _grab(_EXPL_RE, raw)
    return RestAnswer(answer, probability, explanation, answer == "да")


def classify(title: str,
             client: Optional[OmniRouterClient] = None) -> RestAnswer:
    """Спрашивает модель про заголовок окна и возвращает разобранный ответ."""
    if not title:
        return RestAnswer("", None, "", False)
    client = client or OmniRouterClient(log_history=False)
    return parse_rest_answer(client.ask(rest_prompt(title)))


def classify_until_answer(title: str,
                          client: Optional[OmniRouterClient] = None,
                          delay_s: float = 5.0,
                          max_attempts: Optional[int] = None) -> RestAnswer:
    """Дёргает модель про заголовок, пока не придёт разборчатый ответ.

    OmniRouter то и дело отдаёт `Read timed out` / мусор без полей — разовый
    ``classify`` на этом молча глохнет. Здесь же крутимся (пауза ``delay_s``)
    до настоящего «да/нет/не знаю». Пустой заголовок — сети не трогает.
    ``max_attempts=None`` — без потолка (фоновый поток может ждать); ставим
    лимит там, где ждать нельзя. Последний неполный ответ — если уперлись в
    лимит.
    """
    if not title:
        return RestAnswer("", None, "", False)
    client = client or OmniRouterClient(log_history=False)
    attempts = 0
    while True:
        attempts += 1
        res = parse_rest_answer(client.ask(rest_prompt(title)))
        if res.answer:
            return res
        if max_attempts is not None and attempts >= max_attempts:
            return res
        time.sleep(delay_s)


def _grab(pattern: re.Pattern, text: str) -> str:
    """Первая строка-значение после метки (или пустая строка)."""
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _normalize(answer: str) -> str:
    """Сводит поле «Ответ» к да/нет/не знаю (или "" если неясно)."""
    low = answer.lower()
    if re.search(r"не\s*знаю", low):
        return "не знаю"
    if re.search(r"\bнет\b", low):
        return "нет"
    if re.search(r"\bда\b", low):
        return "да"
    return ""
