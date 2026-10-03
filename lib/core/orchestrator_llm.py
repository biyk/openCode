"""LLM-детект команды после промаха Лайи (миксин оркестратора).

По примеру распознавания на доске («распознать все» → try_recognize): если
commands.json и Лайя не дали команду, спрашиваем LLM (OmniRouter/LM Studio
через self._llm) — какой id команды соответствует фраза. Для составных
команд с параметром {{text}} («поставь задачу {текст}») делаем второй
запрос — какая часть фразы является значением параметра, — и исполняем
команду с ним (выбранный параметр переживает confirm на доске).

Гонка двух провайдеров отвечает долго, поэтому вызов детекта идёт из
фонового воркера (`orchestrator_llm_bg`): цикл распознавания не должен
стоять на одной фразе минуту.
"""

from typing import Callable, Optional

from lib.core.errors import swallowed
from lib.voice_cmd.knowledge import COMMAND, LAYA


class OrchestratorLlmMixin:
    """Миксин Orchestrator: LLM-детект id команды + вычленение параметра."""

    def _run_llm_fallback(self, text: str,
                          reply: Optional[Callable[[str], None]] = None,
                          cancelled: Optional[Callable[[], bool]] = None) -> bool:
        """LLM-детект команды; True — фраза обработана (найдена команда).

        Два classify (детект + параметр) идут ВНЕ self._input_lock: под локом
        минута гонки глушила бы весь ввод. Исполнение — в локе: общий слой с
        микрофоном и чатом (озвучка, knowledge, execute). `cancelled` —
        проверка, что фразу не сняли стоп-словом, пока гонка думала.
        """
        cmd_id = self._llm_detect(text)
        if cmd_id is None:
            return False
        param = ""
        if self._matcher.needs_text(cmd_id):
            param = self._llm_extract_param(text, cmd_id)
        if cancelled is not None and cancelled():
            self._output.print_debug(
                f"[LLM] Детект отменён до исполнения: «{text[:40]}»")
            return False
        with self._input_lock:
            prev, self._reply = self._reply, reply
            try:
                self._apply_llm_command(text, cmd_id, param)
            finally:
                self._reply = prev
        return True

    def _apply_llm_command(self, text: str, cmd_id: str, param: str) -> None:
        """Распознанную команду — в laya-корзину и в исполнение.

        Отчитываемся о блокировке по requires как Лайя.
        """
        self._output.print_info(f"[LLM] Команда распознана «{cmd_id}»")
        self._remember_llm_candidate(text, cmd_id, param)
        missing = self._matcher.missing_requires(cmd_id)
        if missing:
            self._report_blocked(cmd_id, missing)
            return
        if self._execute_decision(cmd_id, text, param or None):
            self._output.print_text(cmd_id)
        else:
            self._output.print_error(
                f"[LLM] Команда «{cmd_id}» не выполнена")

    def _llm_fallback_miss(self, text: str) -> None:
        """Промах детекта: фраза в undefined, чату — «не распознано»."""
        self._record_undefined(text)
        self._output.print_info(
            "[Decision] Лайя и LLM: команда не распознана — "
            "фраза в undefined, запрос в opencode не идёт")
        self._chat_not_recognized()

    def _remember_llm_candidate(self, text: str, cmd_id: str,
                                param: str) -> None:
        """Фраза + догадка LLM (команда и параметр) → laya-корзина базы знаний."""
        knowledge = getattr(self, "_knowledge", None)
        if knowledge is None:
            return
        core = self._matcher.core_phrase(text)
        if core:
            knowledge.record(LAYA, core, COMMAND, command=cmd_id,
                             event=param or None)

    def _llm_detect(self, text: str) -> Optional[str]:
        """Спрашивает LLM id команды по смыслу; None, если не распознано."""
        commands = self._matcher.match_config()
        if not commands:
            return None
        valid = list(commands) + [s for s in self._matcher.sequences()
                                  if s not in commands]
        raw = self._ask_llm(self._build_detect_prompt(text, commands))
        return self._extract_id(raw, valid)

    def _build_detect_prompt(self, text: str, commands: dict) -> str:
        """Промпт детекта: перечень команд с примерами + фраза; ответ — id."""
        lines = ["Ты — детектор голосовых команд (фраза с ошибками STT).",
                 "Доступные команды (id — примеры фраз):"]
        for cid, phrases in commands.items():
            lines.append(f"- {cid}: {', '.join(list(phrases)[:4])}")
        lines += [f"Фраза: «{text}»",
                  "Если фраза соответствует команде по смыслу — ответь "
                  "ТОЛЬКО её id одним словом; иначе ровно NONE."]
        return "\n".join(lines)

    def _llm_extract_param(self, text: str, cmd_id: str) -> str:
        """Второй запрос: какая часть фразы — значение параметра {{text}}."""
        examples = self._matcher.match_config().get(cmd_id, [])
        prompt = (
            f"Фраза: «{text}»\n"
            f"Команда: {cmd_id} (примеры ключей: {', '.join(examples[:4])}).\n"
            "В команде есть свободный параметр. Назови ДОСЛОВНО ту часть "
            "фразы, которая является значением параметра — без командного "
            "ключа и без слова-обращения. Ответь только эту часть одной "
            "строкой; если параметра в фразе нет — ровно NONE."
        )
        raw = self._ask_llm(prompt)
        if not raw or not isinstance(raw, str):
            return ""
        val = raw.strip().splitlines()[0].strip().strip('«»"').strip()
        return "" if val.lower() == "none" else val

    def _ask_llm(self, prompt: str) -> Optional[str]:
        """Один ход к LLM: classify() если умеет (гонка, без истории), else ask."""
        llm = getattr(self, "_llm", None)
        if llm is None:
            return None
        classify = getattr(llm, "classify", None)
        try:
            if callable(classify):
                return classify(prompt)
            return llm.ask(prompt)
        except Exception as e:
            swallowed("orchestrator.llm", e)
            return None

    def _extract_id(self, raw: Optional[str], valid: list[str]) -> Optional[str]:
        """Достаёт id команды из ответа LLM с мусором; None если NONE/нет совпад."""
        if not raw or not isinstance(raw, str):
            return None
        text = raw.strip().lower().strip('«»"').strip()
        if text == "none" or not text:
            return None
        first = text.split("\n", 1)[0].strip()
        word = first.split(maxsplit=1)[0].strip(".,;:!?\"'«»()[]")
        for cand in (text, first, word):
            if cand in valid:
                return cand
        best: Optional[str] = None
        pos: Optional[int] = None
        for cid in valid:
            at = text.find(cid)
            if at >= 0 and (pos is None or at < pos):
                best, pos = cid, at
        return best
