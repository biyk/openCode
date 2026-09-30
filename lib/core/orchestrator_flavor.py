"""Оживление ответа креативной фразой от LLM (миксин оркестратора).

После ЛЮБОГО ответа ассистента (успех команды, реплика через `_say`,
итог opencode) в фоне спрашиваем у LLM короткую ободряющую/юмористическую
добавку и произносим (или шлём в чат) СРАЗУ ПОСЛЕ основного ответа — сам
ответ она не задерживает. Генерация через `race.classify` (не пишет в
историю диалога). Всё fail-open: нет LLM/сбой/пусто/стоп — добавка тихо
пропускается. Рекурсии нет: `_emit_flavor` не зовёт `_say`.
"""

import threading
import time

from lib.core.errors import swallowed
from lib.core.flavor import (
    FLAVOR_ENABLED,
    FLAVOR_MAX_LEN,
    FLAVOR_PROMPT_PATH,
    FLAVOR_SPEAK_WAIT_S,
    FLAVOR_TIMEOUT_S,
    build_prompt,
    clean_phrase,
    load_prompt,
)


class OrchestratorFlavorMixin:
    """Миксин Orchestrator: фоновая креативная добавка к любому ответу."""

    def _init_flavor(self) -> None:
        """Читает секцию `flavor` (дефолты — lib.core.flavor) и готовит поток."""
        config = {}
        try:
            config = self._matcher.get_flavor_config()
        except Exception as exc:            # конфиг опционален: живём без него
            swallowed("flavor.config", exc, {})
        if not isinstance(config, dict):    # матчер-заглушка отдаёт не-словарь
            config = {}
        self._flavor_enabled = bool(config.get("enabled", FLAVOR_ENABLED))
        self._flavor_max_len = int(config.get("max_len", FLAVOR_MAX_LEN))
        self._flavor_timeout_s = int(config.get("timeout_s", FLAVOR_TIMEOUT_S))
        self._flavor_wait_s = float(FLAVOR_SPEAK_WAIT_S)
        self._flavor_prompt_path = str(
            config.get("prompt", FLAVOR_PROMPT_PATH))
        self._flavor_busy = False

    def _maybe_flavor(self, command: str, response: str,
                      sink=None) -> None:
        """Запускает фоновую добавку к `response`; no-op, если нельзя.

        sink — явный канал ответа (для opencode: запомненный `reply`, т.к.
        активный канал `self._reply` к моменту фонового ответа мог смениться).
        """
        if not self._flavor_enabled or not (response or "").strip():
            return
        llm = getattr(self, "_llm", None)
        if llm is None or not hasattr(llm, "classify"):
            return
        if self._flavor_busy:
            return
        template = load_prompt(self._flavor_prompt_path)
        if not template:
            return
        prompt = build_prompt(template, command, response)
        self._flavor_busy = True
        channel = sink if sink is not None else getattr(self, "_reply", None)
        threading.Thread(
            target=self._flavor_worker, args=(prompt, channel),
            daemon=True).start()

    def _flavor_worker(self, prompt: str, sink) -> None:
        """Спрашивает LLM, нормализует фразу и отдаёт в `_emit_flavor`."""
        try:
            raw = self._llm.classify(prompt, self._flavor_timeout_s)
            phrase = clean_phrase(raw, self._flavor_max_len)
            if phrase:
                self._emit_flavor(phrase, sink)
        except Exception as exc:            # добавка опциональна: не мешаем
            swallowed("flavor.worker", exc, None)
        finally:
            self._flavor_busy = False

    def _emit_flavor(self, phrase: str, sink) -> None:
        """Вставляет добавку в тот же канал, что и основной ответ."""
        if sink is not None:
            self._chat_send(sink, "\n" + phrase)
            return
        if self._abort_playback.is_set():   # пользователь жмёт стоп — пропускаем
            return
        if not self._wait_flavor_idle():
            return
        if self._abort_playback.is_set():
            return
        self._speaking = True
        self._abort_playback.clear()
        self._speak_async(phrase)

    def _wait_flavor_idle(self) -> bool:
        """Ждёт конца основной озвучки; False — таймаут или прерывание."""
        deadline = time.monotonic() + self._flavor_wait_s
        while self._speaking:
            if self._abort_playback.is_set():
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
        return True
