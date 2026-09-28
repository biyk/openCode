# TOOLTIP: Миксин оркестратора: вопрос вслух и ответ следующей строкой
"""Вопрос ассистента с ожиданием ответа.

Фоновые проверки (task_monitor) спрашивают пользователя вслух. Реплика
сразу после вопроса — это ответ, а не новая команда, поэтому она
перехватывается ДО уровня commands.json и отдаётся колбэку вопроса. Живёт
ответ TASK_ANSWER_TIMEOUT_S секунд: просроченный вопрос снимается, и строка
идёт в общий пайплайн как обычно (иначе ассистент ловил бы «ответ» к
вопросу, заданному полчаса назад).
"""

import time
from dataclasses import dataclass
from typing import Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import TASK_ANSWER_TIMEOUT_S


@dataclass
class PendingAsk:
    """Один заданный и ещё не собранный вопрос."""

    question: str
    label: str
    on_answer: Callable[[str], None]
    deadline: float


class OrchestratorAskMixin:
    """Миксин Orchestrator: ask() + перехват строки-ответа."""

    # Ожидаемый ответ (None — вопроса нет); ставит Orchestrator.__init__.
    _pending_ask: Optional[PendingAsk]

    def say(self, message: str) -> None:
        """Публичная озвучка короткого сообщения (для фоновых проверок)."""
        self._say(message)

    def ask(self, question: str, on_answer: Callable[[str], None],
            label: str = "ask",
            timeout_s: float = TASK_ANSWER_TIMEOUT_S) -> bool:
        """Озвучивает вопрос и ждёт ответ следующей строкой.

        True — вопрос задан. False — уже есть незакрытый вопрос или идёт
        озвучка: вопросы друг на друга не накладываем, проверка попробует
        снова в следующий цикл.
        """
        self._drop_expired_ask()
        if self._pending_ask is not None or self._speaking:
            reason = "ждём ответ" if self._pending_ask else "идёт озвучка"
            self._output.print_info(f"[Ask] «{label}» отложен: {reason}")
            return False
        self._pending_ask = PendingAsk(
            question=question, label=label, on_answer=on_answer,
            deadline=time.monotonic() + timeout_s)
        self._output.print_info(f"[Ask] Вопрос ({label}): «{question}»")
        self._say(question)
        return True

    @property
    def pending_ask(self) -> Optional[str]:
        """Метка ожидаемого ответа (None — вопрос не задан)."""
        pending = self._pending_ask
        return pending.label if pending is not None else None

    def cancel_ask(self) -> None:
        """Снимает ожидаемый вопрос (остановка приложения, отмена)."""
        self._pending_ask = None

    def _drop_expired_ask(self) -> None:
        """Снимает вопрос, оставшийся без ответа после TASK_ANSWER_TIMEOUT_S.

        Без этого один неотвеченный вопрос заблокировал бы все последующие
        (проверка больше никогда не переспросила бы).
        """
        pending = self._pending_ask
        if pending is not None and time.monotonic() >= pending.deadline:
            self._output.print_info(
                f"[Ask] Вопрос «{pending.label}» остался без ответа — снимаю")
            self._pending_ask = None

    def _has_stop_word(self, text: str) -> bool:
        """Есть ли в строке стоп-слово (озвучку оно уже не прервёт)."""
        return any(token in self._stop_words for token in text.lower().split())

    def _take_ask_answer(self, text: str) -> bool:
        """Отдаёт строку ожидающему вопросу. True — строка стала ответом."""
        pending = self._pending_ask
        if pending is None:
            return False
        self._pending_ask = None
        if time.monotonic() >= pending.deadline:
            self._output.print_info(
                f"[Ask] Вопрос «{pending.label}» устарел — строка в пайплайн")
            return False
        if self._has_stop_word(text):
            self._output.print_info(
                f"[Ask] Ответ на «{pending.label}» отменён стоп-словом")
            return True
        self._output.print_info(
            f"[Ask] Ответ на «{pending.label}»: {text}")
        try:
            pending.on_answer(text)
        except Exception as error:               # ответ не роняет цикл STT
            swallowed("ask.on_answer", error)
        return True
