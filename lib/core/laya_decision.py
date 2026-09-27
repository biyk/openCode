"""Decision-слой: клиент к дисижн-модели Laya (laya.exe serve).

Распознанный текст → POST /v1/systemone с критеками команд из секции
`decision` commands.json. Если уверенность >= порога и выбор — известная
команда (не `none`), возвращает (command_id, confidence), иначе None.
Автозапуск сервера (секция `auto_launch`) — по требованию, если /health на порту не отвечает.
"""

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from lib.core.laya_batch import query_batches, run_query
from lib.core.output import TranscriptionOutput
from lib.core.tuning import DECISION_THRESHOLD

DEFAULT_INSTRUCTIONS = (
    "Что пользователь просит сделать голосовому помощнику? "
    "Это распознанная речь с ошибками и лишними словами. "
    "Выбери из существующих команд."
)
# Финальный вопрос после батчей: среди победителей групп выбирается лучший
# (уверенности разных батчей некалиброваны — query_batches, laya_batch).
FINAL_INSTRUCTIONS = (
    "Это распознанная речь с ошибками. В списке — команды-кандидаты, "
    "каждая подошла лучше других в своей группе. Какая из них лучше "
    "всего описывает просьбу? Если ни одна не подходит — none."
)
DEFAULT_NONE_DESCRIPTION = "просто речь, нет команды"
HEALTH_TIMEOUT_S = 240


def _projects_root() -> str:
    """Корень проекта (каталог, где лежит папка lib)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LayaDecision:
    """HTTP-клиент decision-модели Laya + запуск сервера по требованию."""

    def __init__(self, config: dict, output: Optional[TranscriptionOutput] = None,
                 url: Optional[str] = None) -> None:
        self._config = config or {}
        self._output = output or TranscriptionOutput()
        cfg_url = url or self._config.get("url")
        if not cfg_url:
            raise ValueError("decision.url не задан в commands.json")
        self._url = cfg_url.rstrip("/")
        self._threshold = float(self._config.get("threshold", DECISION_THRESHOLD))
        self._timeout = float(self._config.get("timeout", 15))
        self._instructions = self._config.get("instructions", DEFAULT_INSTRUCTIONS)
        self._criteria = dict(self._config.get("criteria", {}))
        self._criteria.setdefault("none", DEFAULT_NONE_DESCRIPTION)
        self._proc: Optional[subprocess.Popen] = None
        self._error_reported = False

    @property
    def available(self) -> bool:
        """Сервер доступен (или будет запущен автозапуском)."""
        return self._health()

    @property
    def url(self) -> str:
        return self._url

    def _print(self, level: str, message: str) -> None:
        printer = getattr(self._output, f"print_{level}", None)
        if printer is not None:
            printer(message)

    def _health(self) -> bool:
        try:
            with urllib.request.urlopen(self._url + "/health", timeout=2) as r:
                return r.status == 200
        except (OSError, ValueError):  # сервер лежит — штатный ответ пробы
            return False

    def ensure_server(self) -> bool:
        """Гарантирует работающий сервер (запускает, если надо)."""
        if self._health():
            return True
        launch = self._config.get("auto_launch")
        if not launch:
            return self._health()
        exe = launch.get("exe")
        model = launch.get("model")
        port = int(launch.get("port", 8080))
        device = launch.get("device", "auto")
        exe_path = os.path.join(_projects_root(), exe) if exe else ""
        model_path = os.path.join(_projects_root(), model) if model else ""
        if not exe_path or not model_path or not os.path.isfile(exe_path) \
                or not os.path.isfile(model_path):
            self._print("error", "[Decision] auto_launch: exe/модель не найдены")
            return self._health()
        self._print("info", f"[Decision] Запуск laya server на :{port}...")
        self._proc = subprocess.Popen(
            [exe_path, "serve", model_path, "--port", str(port),
             "--device", device],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
            if sys.platform == "win32" else 0,
        )
        base = f"http://127.0.0.1:{port}"
        t0 = time.time()
        while time.time() - t0 < HEALTH_TIMEOUT_S:
            if self._proc.poll() is not None:
                self._print("error",
                            f"[Decision] laya server завершился (rc={self._proc.returncode})")
                self._proc = None
                return False
            try:
                with urllib.request.urlopen(base + "/health", timeout=2) as r:
                    if r.status == 200:
                        self._print("info", "[Decision] laya server готов")
                        return True
            except (OSError, ValueError):
                pass  # сервер ещё прогревается, ждём до таймаута
            time.sleep(1)
        self._print("error", "[Decision] laya server не поднялся за "
                    f"{HEALTH_TIMEOUT_S}с")
        return False

    def detect(self, text: str, criteria: Optional[dict] = None,
               instructions: Optional[str] = None,
               threshold: Optional[float] = None,
               on_verdict: Optional[Callable[[str, float], None]] = None,
               ) -> Optional[tuple[str, float, float]]:
        """Вопрос-выбор к Laya: (выбор, уверенность, время запроса в сек.).

        Без аргументов — критерии команды из decision; с criteria/instructions/
        threshold — свой вопрос. Набор больше max_opts режет на батчи
        (laya_batch): победитель каждого батча сравнивается с остальными
        финальным вопросом FINAL_INSTRUCTIONS, и решает именно он. None —
        мимо/ниже порога/нет сервера; on_verdict зовётся вердиктом (choice, c)
        до отбрасывания — виден и none.
        """
        crit = dict(self._criteria if criteria is None else criteria)
        crit.setdefault("none", DEFAULT_NONE_DESCRIPTION)
        limit = self._threshold if threshold is None else threshold
        if not self._health():
            if not self._error_reported:
                self._print("error", f"[Decision] Laya недоступна: {self._url}")
                self._error_reported = True
            return None
        try:
            def ask(sub, ins):
                return run_query(self._url, self._timeout, self._instructions,
                                 text, sub, ins, limit, on_verdict)

            return query_batches(
                crit,
                lambda sub: ask(sub, instructions),
                final=lambda sub: ask(sub, FINAL_INSTRUCTIONS))
        except Exception as e:
            if not self._error_reported:
                self._print("error", f"[Decision] Ошибка запроса Laya: {e}")
                self._error_reported = True
            return None

    def close(self) -> None:
        """Останавливает запущенный сервер (если запускали сами)."""
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


def build_decision(matcher, output: Optional[TranscriptionOutput] = None
                   ) -> Optional[LayaDecision]:
    """Создаёт LayaDecision из commands.json.

    Возвращает None, если decision не включён или сервер недоступен
    (сообщение об ошибке печатается). Используется TranscriptionWorker.
    """
    config = matcher.get_decision_config()
    if not config.get("enabled"):
        return None
    decision = LayaDecision(config, output=output)
    decision.ensure_server()
    if decision.available:
        return decision
    if output is not None:
        output.print_error("[Decision] Laya недоступна — decision-слой "
                           "выключен, работает legacy intent/opencode")
    return None
