# lib/voice_cmd/knowledge_review_levels.py
"""Уровни распознавания фразы на доске: commands.json → Лайя → LLM.

Каждый уровень отвечает вердиктом С ЧИСЛАМИ (выбор, уверенность, порог), а не
голым id: из них knowledge_review_trace собирает след прогона. Лайю здесь НЕ
автозапускаем (в отличие от рантайма): не отвечено — так и пишем в след.
LLM — активный провайдер из providers.json (сейчас гонка omni+lmstudio), а
прямой endpoint из review.json остался фолбэком.
"""

from __future__ import annotations

from typing import Any, Optional

from lib.core.errors import swallowed
from lib.core.tuning import DECISION_THRESHOLD, TITLE_THRESHOLD
from lib.voice_cmd.knowledge_review_recognize import (
    LLM_INSTRUCTIONS, commands_data, llm_question, param_question, parse_llm,
)

NO_LAYA = {"state": "off", "command": "", "confidence": 0.0,
           "threshold": DECISION_THRESHOLD}
# Один ProviderManager на процесс: он сам кэширует клиентов провайдеров.
_MANAGER = None


def laya_config(commands_file: str) -> dict:
    """Секция decision из commands.json (пустой dict, если её нет)."""
    return dict(commands_data(commands_file).get("decision") or {})


def _laya(commands_file: str) -> tuple[Optional[object], float, str]:
    """(клиент Лайи, порог, состояние off|down|ok); автозапуск не делаем."""
    cfg = laya_config(commands_file)
    threshold = float(cfg.get("threshold", DECISION_THRESHOLD))
    if not cfg.get("enabled") or not cfg.get("url"):
        return None, threshold, "off"
    from lib.core.laya_decision import LayaDecision
    try:
        decision = LayaDecision(cfg)
    except ValueError as e:
        swallowed("review.laya_cfg", e)
        return None, threshold, "off"
    if not decision.available:
        return None, threshold, "down"
    return decision, threshold, "ok"


def _ask(decision: Any, text: str, criteria: Optional[dict], threshold: float,
         instructions: Optional[str]) -> dict:
    """Один вопрос Лайе с вердиктом ДО отбрасывания по порогу (on_verdict)."""
    seen: dict = {}

    def cap(choice: str, conf: float) -> None:
        seen.update(command=choice, confidence=conf)

    args: dict = {"threshold": threshold, "on_verdict": cap}
    if criteria is not None:
        args["criteria"] = criteria
    if instructions:
        args["instructions"] = instructions
    try:
        hit = decision.detect(text, **args)
    except Exception as e:
        swallowed("review.laya_ask", e)
        return {"command": "" if seen.get("command") == "none"
                else str(seen.get("command", "")),
                "confidence": float(seen.get("confidence", 0.0)),
                "threshold": threshold, "state": "error"}
    if hit:
        return {"command": str(hit[0]), "confidence": float(hit[1]),
                "threshold": threshold, "state": "hit"}
    # Вердикт `none` в command не оставляем: сканер записал бы его в базу
    # знаний как id команды.
    cmd = "" if seen.get("command") in (None, "none") else str(seen["command"])
    return {"command": cmd, "state": "none" if not cmd else "miss",
            "confidence": float(seen.get("confidence", 0.0)),
            "threshold": threshold}


def laya_verdict(text: str, commands_file: str) -> dict:
    """Вопрос «какая команда»: {state, command, confidence, threshold}."""
    decision, threshold, ready = _laya(commands_file)
    if decision is None:
        return dict(NO_LAYA, state=ready)
    return _ask(decision, text, None, threshold, None)


def laya_guess(text: str, commands_file: str) -> Optional[str]:
    """Только id команды либо None (контракт сканера логов)."""
    verdict = laya_verdict(text, commands_file)
    return verdict["command"] or None


def laya_title(text: str, titles: list[str], commands_file: str) -> dict:
    """Вопрос «какая из задач таблицы»: те же поля, порог Title_threshold."""
    decision, _, ready = _laya(commands_file)
    if decision is None or not titles:
        return {"state": ready if ready != "ok" else "empty",
                "command": "", "confidence": 0.0,
                "threshold": TITLE_THRESHOLD}
    criteria = {t: "задача из списка" for t in titles}
    return _ask(decision, text, criteria, TITLE_THRESHOLD,
                "Какую из задач пользователь имеет в виду? Если ни одну — "
                "none.")


def _manager() -> Any:
    """Ленивый синглтон ProviderManager (чтобы requests не тянулся зря)."""
    global _MANAGER
    if _MANAGER is None:
        from lib.providers.manager import ProviderManager
        _MANAGER = ProviderManager()
    return _MANAGER


def _client(timeout: Optional[float] = None) -> Any:
    """Активный LLM-клиент (сейчас RaceClient); timeout — в конструктор."""
    try:
        kwargs = {} if not timeout else {"timeout": int(timeout)}
        return _manager().get_client(**kwargs)
    except Exception as e:
        swallowed("review.provider", e)
        return None


def llm_level(review: dict) -> str:
    """Подпись уровня LLM по активному провайдеру (для строк следа)."""
    client = _client()
    return f"LLM {client.name}" if client else _direct_label(review)


def _direct_label(review: dict) -> str:
    return f"LLM {review.get('llm_url') or 'не настроен'}"


def llm_ask(prompt: str, review: dict) -> tuple[Optional[str], str]:
    """(ответ, подпись уровня): активный провайдер, затем review.json.

    Фолбэк нужен, чтобы llm_url из review.json не умер вместе с гонкой.
    """
    client = _client(float(review.get("llm_timeout", 300)))
    if client is not None:
        try:
            ask = getattr(client, "classify", None) or client.ask
            answer = ask(prompt)
            if answer and str(answer).strip():
                return str(answer), f"LLM {client.name}"
        except Exception as e:
            swallowed("review.race", e)
    return _direct(prompt, review)


def _direct(prompt: str, review: dict) -> tuple[Optional[str], str]:
    """Прямой OpenAI-совместимый endpoint из review.json (фолбэк гонки)."""
    import requests

    url = str(review.get("llm_url", "")).rstrip("/")
    label = _direct_label(review)
    if not url:
        return None, label
    payload = {"model": review.get("llm_model"),
               "messages": [{"role": "user", "content": prompt}],
               "temperature": 0.0}
    try:
        r = requests.post(f"{url}/chat/completions", json=payload,
                          timeout=float(review.get("llm_timeout", 300)))
        r.raise_for_status()
        answer = (r.json().get("choices") or [{}])[0].get(
            "message", {}).get("content") or ""
        return (answer or None), label
    except Exception as e:
        swallowed("review.llm", e)
        return None, label


def llm_json(text: str, ids: list[str], criteria: dict,
             review: dict) -> tuple[Optional[dict], str]:
    """Полный вопрос (kind/command/event): (разобранный ответ, подпись).

    Инструкции сворачиваются в один prompt: system-роль есть только у прямого
    endpointа, у провайдеров интерфейс — один текст.
    """
    prompt = "\n\n".join([LLM_INSTRUCTIONS, llm_question(text, criteria)])
    answer, label = llm_ask(prompt, review)
    if answer is None:
        return None, label
    return parse_llm(answer, ids), label


def llm_param(text: str, command: str, criteria: dict,
              review: dict) -> tuple[str, str]:
    """Второй вопрос: параметр уже известной команды ("" если NONE)."""
    answer, label = llm_ask(param_question(text, command, criteria), review)
    got = (answer or "").strip()
    if not got or got.lower() in ("none", "нет", "—", "-"):
        return "", label
    return got.splitlines()[0].strip("\"'«» "), label
