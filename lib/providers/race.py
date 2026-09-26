import threading
import time
from typing import Optional
from queue import Empty, Queue

from lib.core.logger import Logger
from lib.providers import BaseLLMClient
from lib.providers.lmstudio import LmStudioClient
from lib.providers.omni import OmniRouterClient


class RaceClient(BaseLLMClient):
    """Клиент, отправляющий запрос одновременно в два провайдера.

    Побеждает тот ответ, который пришёл первым. Каждый провайдер работает
    в своём потоке; первый непустой ответ возвращается наружу сразу,
    не дожидаясь второго потока. Победитель логируется в историю.
    """

    def __init__(self, history_limit: int = 10, timeout: int = 300,
                 omni_model: Optional[str] = None,
                 lmstudio_model: Optional[str] = None):
        self._history_limit = history_limit
        self._timeout = timeout
        self._omni = OmniRouterClient(
            history_limit=history_limit, timeout=timeout, model=omni_model,
            log_history=False, announce=False,
        )
        self._lmstudio = LmStudioClient(
            history_limit=history_limit, timeout=timeout, model=lmstudio_model,
            log_history=False, announce=False,
        )
        self._logger = Logger()
        self._output = None

    @property
    def name(self) -> str:
        return "Race(omni+lmstudio)"

    def _set_output(self, output) -> None:
        """Устанавливает вывод для debug-логирования (вызывается из main)."""
        self._output = output
        self._omni._set_output(output)
        self._lmstudio._set_output(output)

    def _spawn(self, text: str, results: Queue) -> None:
        """Запускает оба провайдера в daemon-потоках."""

        def _run(client: BaseLLMClient, label: str) -> None:
            try:
                answer = client.ask(text)
            except Exception:
                answer = None
            results.put((label, answer))

        threads = [
            threading.Thread(target=_run, args=(self._omni, "omni"), daemon=True),
            threading.Thread(
                target=_run, args=(self._lmstudio, "lmstudio"), daemon=True
            ),
        ]
        for t in threads:
            t.start()

    def ask(self, text: str) -> Optional[str]:
        """Отправляет текст в оба провайдера и возвращает первый ответ."""
        results: Queue = Queue()

        if self._output:
            self._output.print_info(
                f"[LLM Race] Отправляю запрос: omni ({self._omni._model}) "
                f"+ lmstudio ({self._lmstudio._model})"
            )

        self._spawn(text, results)

        winner, answer = self._collect(results)
        if answer is not None:
            if self._output:
                self._output.print_info(
                    f"[LLM Race] Победил: {winner} ({self._winner_name(winner)})"
                )
            self._logger.log_llm("user", text)
            self._logger.log_llm("assistant", answer)
        return answer

    def classify(self, text: str, timeout: Optional[int] = None) -> Optional[str]:
        """Классификация: первый СОДЕРЖАТЕЛЬНЫЙ ответ, без записи в историю.

        Ответы NONE/пустые пропускаются — быстрый «не знаю» от маленькой
        модели не должен убивать медленный правильный ответ большой.
        Ничего не пишет в историю LLM (в отличие от ask).
        """
        results: Queue = Queue()

        if self._output:
            self._output.print_info(
                f"[LLM Race] Классификация: omni ({self._omni._model}) "
                f"+ lmstudio ({self._lmstudio._model})"
            )

        self._spawn(text, results)

        deadline = time.monotonic() + (timeout or self._timeout)
        for _ in range(2):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                label, answer = results.get(timeout=remaining)
            except Empty:
                break
            if (isinstance(answer, str) and answer.strip()
                    and answer.strip().lower() != "none"):
                if self._output:
                    self._output.print_info(
                        "[LLM Race] Классифицировал: "
                        f"{label} ({self._winner_name(label)})"
                    )
                return answer
        return None

    def _winner_name(self, label: str) -> str:
        """Возвращает имя провайдера по метке победителя."""
        if label == "omni":
            return self._omni.name
        if label == "lmstudio":
            return self._lmstudio.name
        return label

    def _collect(self, results: Queue):
        """Достаёт первый ответ, при None — ждёт второй поток."""
        try:
            label, answer = results.get(timeout=self._timeout)
        except Exception:
            return "none", None
        if answer is not None:
            return label, answer
        try:
            return results.get(timeout=self._timeout)
        except Exception:
            return label, None
