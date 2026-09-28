"""Миксин: привязка нераспознанной речи к мероприятиям (start/complete).

Когда Laya не распознала команду, связываем фразу с мероприятием: ищем
по названию среди событий сегодня (кандидат — любое, кроме выполненного
«СОН»), затем среди всех задач таблицы (незапланированное); действие
определяем Laya/эвристикой (по умолчанию — завершение) и исполняем
taskstart/taskdone по чистому заголовку найденного мероприятия.
"""

from typing import Optional

from lib.core.errors import swallowed
from lib.core.tuning import EVENT_ACTION_THRESHOLD, TITLE_THRESHOLD
from lib.google.google_calendar_mutate import DONE_COLOR
from lib.sleep_event import SLEEP_TITLE_RE
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
# Маркеры начала мероприятия: при них фраза = «старт», иначе — «завершил».
# «нач» ловит и несовершенный («начинаю»), и совершенный («начал/начать»)
# вид; «сначала» не попадает (начинается с «сн»).
_START_MARKERS = ("нач", "приступ", "собира", "старт", "иду", "пош",
                  "буду", "сейчас")


def is_undone(ev: dict) -> bool:
    """True, если событие НЕ выполнено (colorId != DONE_COLOR='7')."""
    return ev.get("colorId") != DONE_COLOR


def is_event_candidate(ev: dict) -> bool:
    """Кандидат event-match: «СОН» — только невыполненный (иначе не «спим»
    дважды); прочие мероприятия (календарь и таблица) — любые, в т.ч. закрытые."""
    if SLEEP_TITLE_RE.search(ev.get("summary") or ""):
        return is_undone(ev)
    return True


class OrchestratorEventMatchMixin:
    """Fallback: нераспознанная речь → привязка к мероприятию (старт/финиш)."""

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
        """Связывает фразу с мероприятием (сегодня/таблица) и исполняет.

        True — команда выполнена, False — совпадения нет (уходим в
        LLM-детект команды).
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
            try:
                event = finder.find_task_event(core, filter_fn=is_event_candidate,
                                               report=report)
            except OSError as e:
                # Сетевая нестабильность (SSLEOFError у протухшего
                # keep-alive) — одна повторная попытка новым соединением.
                swallowed("event_match.retry", e)
                event = finder.find_task_event(core,
                                               filter_fn=is_event_candidate,
                                               report=report)
        except Exception as e:
            swallowed("event_match.find", e)
            return False
        if event is None:
            self._output.print_info(
                "[EventMatch] Мероприятие не найдено (ни среди событий "
                "сегодня, ни среди задач таблицы)")
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
        self._output.print_info(
            f"[EventMatch] Действие={action} → {cmd_id}")
        # Исполняем по чистому заголовку найденного мероприятия (не по
        # коверканной фразе): {{text}} = summary → taskdone/taskstart
        # резолвят его через find_task_event (календарь → таблица).
        return self._execute_decision(cmd_id, text, event["summary"])

    def _execute_event_action(self, action: str, event_title: str) -> bool:
        """Подтверждённая синоним-фраза мероприятия: старт/финиш напрямую.

        Мимо нечёткого find_task_event и Лайи: заголовок уже известен из
        базы знаний, идёт как {{text}} в taskstart/taskdone.
        """
        cmd_id = "taskstart" if action == "start" else "taskdone"
        self._output.print_info(
            f"[Knowledge] Мероприятие: «{event_title}» → {action} ({cmd_id})")
        if self._matcher.needs_text(cmd_id):
            ok = self._matcher.execute_by_id(cmd_id, (event_title,))
        else:
            ok = self._matcher.execute_by_id(cmd_id)
        if ok:
            self._chat_done(cmd_id)
        return ok

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
        """Эвристика: явный маркер начала → start, иначе по умолчанию complete.

        Фраза совпала с мероприятием и не содержит «начинаю/иду/буду» —
        считаем, что пользователь его уже закончил (базовое поведение:
        сказал про мероприятие = закрыл его).
        """
        tokens = text.lower().replace("ё", "е").split()
        for token in tokens:
            if token.startswith(_START_MARKERS):
                return "start"
        return "complete"
