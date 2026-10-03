# lib/voice_cmd/knowledge_review_detect.py
"""Две фазы распознавания фразы на доске и его текстовый след.

Фаза 1 — «какая команда»: оценки commands.json (те же match-шаблоны и порог,
что в рантайме), затем Лайя, затем LLM; останов на первом принятом вердикте,
остальные уровни записаны «пропущено» с причиной. Фаза 2 — параметр команды:
для задачных (taskstart/taskdone, kind start/finish) это поиск задачи по
списку real_life_tasks с тем же скорингом и порогом, что у EventMatch; для
free-text — остаток фразы после ключа. Параметр, не дотянувший до порога, НЕ
записывается: в следе видно, сколько он набрал и почему отброшен.

try_recognize — прежнее имя точки входа (её зовут bulk и HTTP-API).
"""

from __future__ import annotations

from typing import Optional

from lib.voice_cmd import knowledge_review_levels as lv
from lib.voice_cmd import knowledge_review_trace as kt
from lib.voice_cmd.knowledge_review_board import sheet_task_titles
from lib.voice_cmd.knowledge_review_recognize import (
    commands_data, commands_meta, free_text_ids,
)

# Параметр этих команд — название задачи из таблицы (тот же список, что
# подсказка на доске).
TASK_COMMANDS = ("taskstart", "taskdone")
_LAYA_WHY = {"off": "decision выключен в commands.json",
             "down": "сервер Лайи не отвечает",
             "error": "ошибка запроса (в логе доски)",
             "empty": "список задач пуст"}
_NOTHING = {"via": "", "command": "", "kind": "none", "event": "",
            "rest": "", "key": ""}


def try_recognize(text: str, commands_file: str, review: dict,
                  titles: Optional[list[str]] = None) -> dict:
    """Фраза → {via, kind, command, event, trace} с числами в следе."""
    data = commands_data(commands_file)
    ids, criteria = commands_meta(data)
    match = data.get("match") or {}
    tr = kt.Trace(text)
    llm_name = lv.llm_level(review)
    got = _phase1(tr, text, commands_file, match, ids, criteria, review,
                  llm_name)
    got["text"] = text
    param = _phase2(tr, got, data, criteria, review, commands_file, llm_name,
                    titles)
    tr.result(got["command"], kt.key_of(match, got["command"], text), param)
    return {"via": got["via"] or "none",
            "kind": got["kind"] if got["via"] else "none",
            "command": got["command"], "event": param, "trace": tr.text()}


def _phase1(tr: kt.Trace, text: str, commands_file: str, match: dict,
            ids: list[str], criteria: dict, review: dict,
            llm_name: str) -> dict:
    """Фаза 1: три вопроса «какая команда», стоп на первом принятом."""
    tr.phase("1\tопределение команды")
    cid, tpl, score = kt.best_template(match, text)
    ok = bool(cid) and score >= kt.MATCH_THRESHOLD
    tr.level("commands.json", cid, score, kt.MATCH_THRESHOLD, ok,
             f'ключ "{tpl}"' if tpl else "нет похожих шаблонов")
    if ok:
        why = "фаза 1 завершена: commands.json"
        tr.skipped("Laya", why)
        tr.skipped(llm_name, why)
        return {"via": "commands", "command": cid, "kind": "command",
                "event": "", "rest": _after(text, tpl), "key": tpl}
    verdict = lv.laya_verdict(text, commands_file)
    if _laya_line(tr, verdict):
        tr.skipped(llm_name, "фаза 1 завершена: Laya")
        return {"via": "laya", "command": verdict["command"],
                "kind": "command", "event": "", "rest": "", "key": tpl}
    return _llm(tr, text, ids, criteria, review, llm_name)


def _laya_line(tr: kt.Trace, v: dict, name: str = "Laya") -> bool:
    """Строка Лайи; True = вердикт принят. Без сервера — честный пропуск."""
    if v["state"] in _LAYA_WHY:
        tr.skipped(name, _LAYA_WHY[v["state"]])
        return False
    tr.level(name, v["command"] or "none", v["confidence"], v["threshold"],
             v["state"] == "hit", "уверенность модели")
    return v["state"] == "hit"


def _llm(tr: kt.Trace, text: str, ids: list[str], criteria: dict,
         review: dict, llm_name: str) -> dict:
    """Последний уровень фазы 1: полный вопрос LLM (kind/command/event)."""
    guess, label = lv.llm_json(text, ids, criteria, review)
    if guess is None:
        tr.level(label, "нет ответа", None, None, False)
        return dict(_NOTHING)
    tr.level(label, guess["command"] or guess["event"] or "none", None, None,
             guess["kind"] != "none", "JSON-вердикт")
    if guess["kind"] == "none":
        return dict(_NOTHING)
    return {"via": "llm", "command": guess["command"], "kind": guess["kind"],
            "event": guess["event"], "rest": "", "key": ""}


def _phase2(tr: kt.Trace, got: dict, data: dict, criteria: dict,
            review: dict, commands_file: str, llm_name: str,
            titles: Optional[list[str]]) -> str:
    """Фаза 2: параметр распознанной команды (или честный «не нужна»)."""
    text = got["text"]
    if not got["via"]:
        tr.phase("2\tне нужна: команда не определена")
        return ""
    cid = got["command"]
    tasky = got["kind"] in ("start", "finish") or cid in TASK_COMMANDS
    if not tasky and not (cid and cid in free_text_ids(data)):
        tr.phase("2\tне нужна: у команды нет параметра")
        return ""
    tr.phase(f"2\tпараметры команды {cid or got['kind']}")
    if tasky:
        return _task_param(tr, text, got, criteria, review, commands_file,
                           llm_name, titles)
    return _free_param(tr, got, criteria, review, llm_name)


def _task_param(tr: kt.Trace, text: str, got: dict, criteria: dict,
                review: dict, commands_file: str, llm_name: str,
                titles: Optional[list[str]]) -> str:
    """Параметр-задача: commands.json → Лайя по списку → LLM; порог 0.75."""
    names = sheet_task_titles() if titles is None else titles
    tr.note("это задача: поиск по списку задач таблицы, порог "
            f"{kt.TITLE_THRESHOLD:.2f}")
    if got["rest"]:
        taken = _scored(tr, "commands.json", got["rest"], names,
                        "слова после ключа")
        if taken:
            why = "фаза 2 завершена: commands.json"
            tr.skipped("Laya", why)
            tr.skipped(llm_name, why)
            return taken
    else:
        tr.skipped("commands.json", "слов после ключа нет"
                   if got["via"] == "commands"
                   else f"команду дала {got['via']}")
    verdict = lv.laya_title(text, names, commands_file)
    if _laya_line(tr, verdict):
        tr.skipped(llm_name, "фаза 2 завершена: Laya")
        return verdict["command"]
    cand, label = _llm_param(got, text, criteria, review, llm_name)
    if not cand:
        return ""
    return _scored(tr, label, cand, names, "параметр от LLM")


def _llm_param(got: dict, text: str, criteria: dict, review: dict,
               llm_name: str) -> tuple[str, str]:
    """Параметр от LLM: берём ответ фазы 1, иначе задаём второй вопрос."""
    if got["event"]:
        return got["event"], llm_name
    if got["kind"] == "command" and got["via"] == "llm":
        # В фазе 1 event не спрашивали (он нужен только для start/finish).
        return lv.llm_param(text, got["command"], criteria, review)
    if got["via"] == "llm":
        return "", llm_name
    return lv.llm_param(text, got["command"] or got["kind"], criteria, review)


def _scored(tr: kt.Trace, level: str, cand: str, names: list[str],
            tail: str) -> str:
    """Оценка кандидата по задачам таблицы: строка следа + принятое значение."""
    title, score = kt.score_titles(cand, names)
    ok = score >= kt.TITLE_THRESHOLD
    tr.level(level, title or cand, score, kt.TITLE_THRESHOLD, ok, tail)
    return title if ok else ""


def _free_param(tr: kt.Trace, got: dict, criteria: dict, review: dict,
                llm_name: str) -> str:
    """Free-text {{text}}: остаток после ключа или ответ LLM; порога нет."""
    tr.note("свободный текст {{text}}: сравнивать не с чем, порог не нужен")
    if got["rest"]:
        tr.level("commands.json", got["rest"], None, None, True,
                 "слова после ключа")
        tr.skipped("Laya", "фаза 2 завершена: commands.json")
        tr.skipped(llm_name, "фаза 2 завершена: commands.json")
        return got["rest"]
    tr.skipped("commands.json", "слов после ключа нет")
    tr.skipped("Laya", "Лайя отвечает только на вопрос «какая команда»")
    cand, label = _llm_param(got, got["text"], criteria, review, llm_name)
    if not cand:
        tr.level(label, "нет ответа", None, None, False, "параметра нет")
        return ""
    tr.level(label, cand, None, None, True, "свободный текст от LLM")
    return cand


def _after(text: str, tpl: str) -> str:
    """Слова фразы после ключа (параметр commands.json — как в рантайме)."""
    words = kt.norm(text).split()
    return " ".join(words[len(kt.norm(tpl).split()):])
