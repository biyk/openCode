# TOOLTIP: Миксин оркестратора: вопрос вслух и ответ следующей строкой (с ключом команды — в уровни)
"""Вопрос ассистента с ожиданием ответа.

Фоновые проверки (task_monitor) спрашивают пользователя вслух. Реплика
сразу после вопроса — это ответ, а не новая команда, поэтому она
перехватывается ДО уровня commands.json и отдаётся колбэку вопроса. Живёт
ответ TASK_ANSWER_TIMEOUT_S секунд: просроченный вопрос снимается, и строка
идёт в общий пайплайн как обычно (иначе ассистент ловил бы «ответ» к
вопросу, заданному полчаса назад). Снятие вопроса зовёт `on_expire` — так
его копия с кнопками убирается из Telegram, пока пользователь не ответил на
уже мёртвый вопрос (§4.7).

Вопрос с ключом команды (`prefix`) ждёт не заметку, а команду: ответ
дописывается этим ключом («начал прогулка») и уходит в уровни §10, минуя
требование триггера — строка уже адресована ассистенту. Без ключа фраза
попадала в лог «просто фразой» и не доходила ни до скриптов, ни до LLM.
Ключ НЕ дописывается, если «голая» строка — другая команда: «алиса быстрее»
это rateup, а не название задачи, и дописанный «начал» уводил её в taskstart,
где настоящая команда и терялась.
"""

import time
from dataclasses import dataclass
from typing import Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import TASK_ANSWER_TIMEOUT_S


def _with_key(prefix: str, text: str) -> str:
    """Фраза с ключом команды в начале; уже начатую фразу не дублируем."""
    phrase = (text or "").strip()
    if phrase.lower().startswith(prefix.lower()):
        return phrase
    return f"{prefix} {phrase}".strip()


@dataclass
class PendingAsk:
    """Один заданный и ещё не собранный вопрос."""

    question: str
    label: str
    on_answer: Callable[[str], None]
    deadline: float
    # Что сделать, когда вопрос умер без ответа (снять реплику из чата).
    on_expire: Optional[Callable[[], None]] = None
    # Ключ команды, дописываемый к ответу (None — ответ собирает колбэк).
    prefix: Optional[str] = None


class OrchestratorAskMixin:
    """Миксин Orchestrator: ask() + перехват строки-ответа."""

    # Ожидаемый ответ (None — вопроса нет); ставит Orchestrator.__init__.
    _pending_ask: Optional[PendingAsk]

    def say(self, message: str) -> None:
        """Публичная озвучка короткого сообщения (для фоновых проверок)."""
        self._say(message)

    def ask(self, question: str, on_answer: Callable[[str], None],
            label: str = "ask",
            timeout_s: float = TASK_ANSWER_TIMEOUT_S,
            on_expire: Optional[Callable[[], None]] = None,
            prefix: Optional[str] = None) -> bool:
        """Озвучивает вопрос и ждёт ответ следующей строкой.

        True — вопрос задан. False — уже есть незакрытый вопрос или идёт
        озвучка: вопросы друг на друга не накладываем, проверка попробует
        снова в следующий цикл. `on_expire` зовётся, если ответ так и не
        пришёл (вопрос просрочен) — у чата есть шанс убрать свой вопрос.
        `prefix` — ключ команды, к которому относится ответ: строка
        дописывается им и идёт в пайплайн как команда (см. модуль-докку).
        """
        self._drop_expired_ask()
        if self._pending_ask is not None or self._speaking:
            reason = "ждём ответ" if self._pending_ask else "идёт озвучка"
            self._output.print_info(f"[Ask] «{label}» отложен: {reason}")
            return False
        self._pending_ask = PendingAsk(
            question=question, label=label, on_answer=on_answer,
            deadline=time.monotonic() + timeout_s, on_expire=on_expire,
            prefix=prefix)
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
            self._expire_ask(pending)

    def _expire_ask(self, pending: PendingAsk) -> None:
        """Зовёт on_expire вопроса (снять его реплику из Telegram-чата).

        Сбой колбэка не должен мешать снять вопрос: его уже убрали из
        ожидаемых, поэтому исключение только логируется.
        """
        if pending.on_expire is None:
            return
        try:
            pending.on_expire()
        except Exception as error:                # снятие не роняет цикл STT
            swallowed("ask.on_expire", error)

    def _has_stop_word(self, text: str) -> bool:
        """Есть ли в строке стоп-слово (озвучку оно уже не прервёт)."""
        return any(token in self._stop_words for token in text.lower().split())

    def _is_other_command(self, text: str, prefix: str) -> bool:
        """Матчится ли «голая» строка как команда, отличный от ключа.

        Ответом на вопрос считается название задачи, а не новая команда:
        матчер спрашиваем дважды — саму строку (с триггером) и ключ. Совпал
        id ключа — строка относится к вопросу; другой id — вопрос остаётся
        висеть, а строка уходит в общий пайплайн как команда.
        """
        core_id, _ = self._matcher.find_command(text, require_trigger=True)
        if core_id is None:
            return False
        key_id, _ = self._matcher.find_command(prefix, require_trigger=False)
        return core_id != key_id

    def _take_ask_answer(self, text: str) -> bool:
        """Отдаёт строку ожидающему вопросу. True — строка стала ответом.

        Принятую строку печатаем здесь же (`process_text` её больше не
        печатает): вопрос с ключом команды печатается уже командой — иначе
        ответ оставался «просто фразой» и в логе, и в уровнях (§4.3).
        """
        pending = self._pending_ask
        if pending is None:
            return False
        self._pending_ask = None
        if time.monotonic() >= pending.deadline:
            self._output.print_info(
                f"[Ask] Вопрос «{pending.label}» устарел — строка в пайплайн")
            self._expire_ask(pending)
            return False
        if self._has_stop_word(text):
            self._output.print_text(text)
            self._output.print_info(
                f"[Ask] Ответ на «{pending.label}» отменён стоп-словом")
            return True
        if not pending.prefix or not text.strip():
            self._output.print_text(text)
            self._output.print_info(
                f"[Ask] Ответ на «{pending.label}»: {text}")
            return self._note_answer(pending, text)
        if pending.prefix and self._is_other_command(text, pending.prefix):
            # Строка — команда, а не ответ: вопрос ждём дальше, её в пайплайн.
            self._pending_ask = pending
            self._output.print_info(
                f"[Ask] «{pending.label}» пропущен: строка — другая команда")
            return False
        line = _with_key(pending.prefix, text)
        self._output.print_text(line)
        self._output.print_info(
            f"[Ask] Ответ на «{pending.label}» — команда: {line}")
        if self._process_commands_level(line, forced=True):
            return True
        # Ключ не помог (например, такой задачи в таблице нет) — у вопроса
        # остаётся собственный ответ.
        return self._note_answer(pending, text)

    def _note_answer(self, pending: PendingAsk, text: str) -> bool:
        """Зовёт колбэк вопроса; его сбой не должен ронять цикл STT."""
        try:
            pending.on_answer(text)
        except Exception as error:                # ответ не роняет цикл STT
            swallowed("ask.on_answer", error)
        return True
