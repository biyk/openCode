"""Миксин: привязка нераспознанной речи к мероприятиям дня (start/complete).

Когда Laya не распознала команду, пробуем связать фразу с мероприятием
на сегодня: находим НЕвыполненную задачу (colorId != '7' — источник
истины, Calendar) по названию, определяем начало/завершение через Laya
или эвристику прошедшего времени, запускаем taskstart/taskdone.
"""

from typing import Optional

from lib.core.errors import swallowed
from lib.core.tuning import EVENT_ACTION_THRESHOLD, TITLE_THRESHOLD
from lib.google.google_calendar_mutate import DONE_COLOR
from lib.task_start import TaskStartHandler

# Критерии для Laya-вопроса «начал или завершил» (бинарный выбор).
EVENT_ACTION_CRITERIA = {
    "start": (
        "пользователь начинает или только что приступил к мероприятию: "
        "начинаю, приступаю, сейчас буду, взялся за, иду делать"
    ),
    "complete": (
        "пользователь уже завершил, закончил или сделал мероприятие "
        "(прошедшее время): почистил, сделал, приготовил, закончил, "
        "выполнил, сходил, убрал"
    ),
}
EVENT_ACTION_INSTRUCTIONS = (
    "Пользователь говорит о сегодняшнем мероприятии. "
    "Он его НАЧИНАЕТ или уже ЗАВЕРШИЛ?"
)
# Порог бинарного вопроса «начал/завершил» — в lib.core.tuning.

# Окончания прошедшего времени для фолбэк-эвристики.
_PAST_ENDINGS = ("ил", "ал", "ел", "ла", "ло", "ли", "лись", "лся")
# Местоимения 1/2-го лица: фраза про самого говорящего, а не просьба.
_SELF_PRONOUNS = {"я", "мы", "ты", "мне", "мой", "моё", "мое", "моя"}


def is_undone(ev: dict) -> bool:
    """True, если событие НЕ выполнено (colorId != DONE_COLOR='7')."""
    return ev.get("colorId") != DONE_COLOR


class OrchestratorEventMatchMixin:
    """Fallback: нераспознанная речь → привязка к невыполненному событию."""

    def _is_self_report(self, text: str) -> bool:
        """True, если фраза — само-отчёт, а не просьба к ассистенту.

        «я почистил зубы», «закончил зарядку» — про действия говорящего
        (местоимение 1/2-го лица или глагол прошедшего времени). Обычные
        императивы («открой ютуб», «громче») — не само-отчёт.
        """
        core = self._matcher.core_phrase(text)
        if not isinstance(core, str):
            return False
        tokens = core.lower().replace("ё", "е").split()
        if tokens and tokens[0] in _SELF_PRONOUNS:
            return True
        return any(len(t) > 4 and t.endswith(e)
                   for t in tokens for e in _PAST_ENDINGS)

    def _get_event_matcher(self) -> TaskStartHandler:
        """Лениво создаёт TaskStartHandler на экземпляре оркестратора."""
        matcher = getattr(self, "_event_matcher", None)
        if matcher is None:
            matcher = TaskStartHandler()
            self._event_matcher = matcher
        return matcher

    def _try_event_match(self, text: str) -> bool:
        """Связывает фразу с невыполненным мероприятием сегодня.

        True — команда выполнена, False — совпадения нет (уходим в
        заглушку OmniRouter).
        """
        core = self._matcher.core_phrase(text)
        if not core or not core.strip():
            return False
        self._output.print_info(
            f"[EventMatch] Ищу нераспознанное мероприятие для «{core}» "
            f"(порог {TITLE_THRESHOLD}):")

        def report(summary: str, score: float) -> None:
            self._output.print_info(
                f"[EventMatch]   «{summary}» \u2192 {score:.2f}")
        try:
            finder = self._get_event_matcher()
            event = finder.find_task_event(core, filter_fn=is_undone,
                                           report=report)
        except Exception as e:
            swallowed("event_match.find", e)
            return False
        if event is None:
            self._output.print_info(
                "[EventMatch] Невыполненное мероприятие сегодня "
                "не найдено (ни одно не выше порога)")
            return False
        task_uuid = finder.event_uuid(event)
        if task_uuid is None:
            self._output.print_info(
                f"[EventMatch] В «{event['summary']}» нет uuid")
            return False
        self._output.print_info(
            f"[EventMatch] Найдено: «{event['summary']}» "
            f"(uuid={task_uuid[:8]}...)")
        action = self._detect_event_action(core)
        if action is None:
            self._output.print_info("[EventMatch] Действие не определено")
            return False
        cmd_id = "taskstart" if action == "start" else "taskdone"
        self._output.print_info(f"[EventMatch] Действие={action} → {cmd_id}")
        return self._execute_decision(cmd_id, text)

    def _detect_event_action(self, core: str) -> Optional[str]:
        """Определяет «start» или «complete»: Laya → эвристика."""
        decision = getattr(self, "_decision", None)
        if decision is not None:
            try:
                detected = decision.detect(
                    core,
                    criteria=EVENT_ACTION_CRITERIA,
                    instructions=EVENT_ACTION_INSTRUCTIONS,
                    threshold=EVENT_ACTION_THRESHOLD,
                )
            except Exception as e:
                detected = swallowed("event_match.action", e, None)
            if detected is not None:
                return detected[0]
        return self._detect_action_heuristic(core)

    @staticmethod
    def _detect_action_heuristic(text: str) -> str:
        """Эвристика: глагол прошедшего времени → complete, иначе start."""
        tokens = text.lower().replace("ё", "е").split()
        for token in tokens:
            if len(token) > 4 and any(
                    token.endswith(e) for e in _PAST_ENDINGS):
                return "complete"
        return "start"
