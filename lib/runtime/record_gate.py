# TOOLTIP: Шлюз захвата микрофона: глушим запись, пока с динамиков играет медиа
"""Правило: звук идёт НЕ через разрешённое устройство и что-то играет → не пишем.

Медиа с колонок попадает в микрофон, и ассистент начинает распознавать чужую
речь — ложные вызовы и обрывки песен вместо команд. В наушниках утечки нет,
поэтому там запись работает как обычно; «наушники» задаются подстрокой имени
устройства в `record_gate.allowed_device`.

Опрос живёт в daemon-потоке (как task_monitor): колбэк sounddevice — поток
реального времени, COM-вызовы туда пускать нельзя, он только читает готовый
флаг `blocked`. Свою озвучку в медиа не считаем: TTS играет из дочерних
powershell/mpg123 (lib/synth/tts_playback.py), и учти мы её — шлюз закрывался
бы сразу после каждой произнесённой фразы.
"""
import threading
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import (RECORD_GATE_ALLOWED_DEVICE,
                             RECORD_GATE_IGNORED_PROCESSES, RECORD_GATE_MIN_PEAK,
                             RECORD_GATE_POLL_S)
from lib.runtime.audio_devices import (active_session_processes,
                                       default_device_name)
from lib.runtime.win_com import co_initialize


def media_is_playing(ignored: tuple[str, ...],
                     min_peak: float = RECORD_GATE_MIN_PEAK) -> bool:
    """True, если на устройстве сейчас слышен звук не от наших плееров.

    Голос ассистента — это тоже динамики; учти мы его, шлюз закрывался бы
    сразу после каждой произнесённой фразы, поэтому процессы из `ignored`
    (наш TTS/плеер) медиа не считаются.
    """
    return any(p not in ignored
               for p in active_session_processes(min_peak))


class RecordGate:
    """Фоновый опрос «микрофон писать нельзя»; аудио-колбэк читает `blocked`."""

    def __init__(self, allowed_device: str, output: Any = None,
                 poll_s: float = RECORD_GATE_POLL_S,
                 device_name: Callable[[], Optional[str]] = default_device_name,
                 media_playing: Callable[[], bool] = lambda: False) -> None:
        self.allowed = (allowed_device or "").strip().casefold()
        self._output = output
        self._poll_s = poll_s
        self._device_name = device_name
        self._media_playing = media_playing
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._blocked = False
        self._changed = False

    @property
    def blocked(self) -> bool:
        """Закрыт ли сейчас захват (кэш последнего опроса)."""
        return self._blocked

    def take_change(self) -> bool:
        """True один раз после любого переключения (сбросить распознаватель)."""
        changed, self._changed = self._changed, False
        return changed

    # ---------- Поток ----------

    def start(self) -> None:
        """Запускает daemon-поток опроса (COM инициализируется в нём самом)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="record-gate")
        self._thread.start()

    def stop(self) -> None:
        """Останавливает поток опроса."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        co_initialize()
        while not self._stop.wait(self._poll_s):
            try:
                self.tick()
            except Exception as error:                # цикл не должен умирать
                swallowed("record_gate.tick", error)

    # ---------- Один опрос (публично для тестов) ----------

    def tick(self) -> bool:
        """Опрашивает устройство и медиа; возвращает актуальный `blocked`.

        Сбой любого запроса — открываем запись (fail-open): ассистент,
        оглохший из-за сломанной проверки, хуже, чем оглохший из-за музыки.
        """
        try:
            name = self._device_name()
        except Exception as error:
            name = swallowed("record_gate.device", error, None)
        if not self.allowed or name is None:
            return self._set(False)
        if self.allowed in name.casefold():
            return self._set(False)                   # наушники: утечки нет
        try:
            playing = bool(self._media_playing())
        except Exception as error:
            playing = swallowed("record_gate.media", error, False)
        return self._set(playing)

    def _set(self, blocked: bool) -> bool:
        """Применяет состояние; переключение — одно сообщение в консоль."""
        if blocked == self._blocked:
            return blocked
        self._blocked = blocked
        self._changed = True
        if self._output is not None:
            self._output.print_info(f"[RecordGate] {self._message(blocked)}")
        return blocked

    def _message(self, blocked: bool) -> str:
        """Что написать в консоль при переключении шлюза."""
        if not blocked:
            return "Запись открыта"
        return (f"Запись заглушена: играет медиа, а звук идёт не через "
                f"«{self.allowed}»")


def build_record_gate(matcher: Any, output: Any) -> Optional[RecordGate]:
    """Собирает шлюз по секции `record_gate` commands.json (не запуская поток).

    Ключи секции: enabled, allowed_device (подстрока имени «тихого»
    устройства), poll_s, min_peak (ниже какого порога пик-метра сессия тишина),
    ignored_processes (чей звук не считать медиа); чего нет — берём из
    lib.core.tuning. None — секция выключена.
    Поток опросов запускает владелец цикла захвата (worker.run).
    """
    config = matcher.get_record_gate_config()
    if not config.get("enabled"):
        return None
    allowed = str(config.get("allowed_device", RECORD_GATE_ALLOWED_DEVICE))
    poll_s = float(config.get("poll_s", RECORD_GATE_POLL_S))
    min_peak = float(config.get("min_peak", RECORD_GATE_MIN_PEAK))
    ignored = tuple(str(p).lower() for p in
                    config.get("ignored_processes",
                               RECORD_GATE_IGNORED_PROCESSES))
    output.print_info(
        f"[RecordGate] Микрофон глохнет при медиа вне «{allowed}» "
        f"(опрос {poll_s:.1f} с)")
    return RecordGate(
        allowed_device=allowed, output=output, poll_s=poll_s,
        media_playing=lambda: media_is_playing(ignored, min_peak))
