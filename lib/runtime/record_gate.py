# TOOLTIP: Шлюз захвата микрофона: глушим запись, пока с динамиков идёт звук
"""Правило: звук идёт НЕ через разрешённое устройство и на нём есть звук → не пишем.

Медиа с колонок попадает в микрофон, и ассистент начинает распознавать чужую
речь — ложные вызовы и обрывки песен вместо команд. В наушниках утечки нет,
поэтому там запись работает как обычно; «наушники» задаются подстрокой имени
устройства в `record_gate.allowed_device`.

Своя озвучка — такой же звук с колонок: наслушавшись себя, ассистент делает
команды из обрывков собственных фраз. Поэтому TTS пушем сообщает шлюзу о начале
и конце воспроизведения (`RecordGate.voice`), а скидка по именам процессов-
плееров по умолчанию выключена.

Опрос живёт в daemon-потоке (как task_monitor): колбэк sounddevice — поток
реального времени, COM-вызовы туда пускать нельзя, он только читает готовый
флаг `blocked`.
"""
import threading
import time
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import (RECORD_GATE_ALLOWED_DEVICE,
                             RECORD_GATE_IGNORED_PROCESSES, RECORD_GATE_MIN_PEAK,
                             RECORD_GATE_POLL_S, RECORD_GATE_VOICE_TAIL_S)
from lib.runtime.audio_devices import (active_session_processes,
                                       default_device_name)
from lib.runtime.win_com import co_initialize


def media_is_playing(ignored: tuple[str, ...],
                     min_peak: float = RECORD_GATE_MIN_PEAK) -> bool:
    """True, если на устройстве сейчас слышен звук не из списка `ignored`.

    Скидки по умолчанию пустые: голос ассистента — тоже звук с колонок, а
    считать его «не медиа» означало слушать самому себя. Список остаётся
    ручкой на случай, когда какой-то источник нужно разрешить.
    """
    return any(p not in ignored
               for p in active_session_processes(min_peak))


class RecordGate:
    """Фоновый опрос «микрофон писать нельзя»; аудио-колбэк читает `blocked`."""

    def __init__(self, allowed_device: str, output: Any = None,
                 poll_s: float = RECORD_GATE_POLL_S,
                 device_name: Callable[[], Optional[str]] = default_device_name,
                 media_playing: Callable[[], bool] = lambda: False,
                 voice_tail_s: float = RECORD_GATE_VOICE_TAIL_S) -> None:
        self.allowed = (allowed_device or "").strip().casefold()
        self._output = output
        self._poll_s = poll_s
        self._device_name = device_name
        self._media_playing = media_playing
        self._tail_s = voice_tail_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._blocked = False
        self._changed = False
        # Состояние: опрос в своём потоке + пуш из потока озвучки.
        self._lock = threading.Lock()
        self._loud = False         # устройство «не наушники» (кэш последнего tick)
        self._media = False        # на нём что-то играет (кэш того же tick)
        self._voice = 0            # сколько наших плееров звучит сейчас
        self._voice_until = 0.0    # конец хвоста после последнего voice(False)

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
        quiet = (not self.allowed or name is None
                 or self.allowed in name.casefold())   # наушники: утечки нет
        playing = False
        if not quiet:
            try:
                playing = bool(self._media_playing())
            except Exception as error:
                playing = swallowed("record_gate.media", error, False)
        with self._lock:
            self._loud = not quiet
            self._media = playing
            return self._apply()

    def voice(self, active: bool) -> None:
        """Пуш из TTS: наша озвучка началась/закончилась (без COM, из её потока).

        Шлюз закрывается в момент, когда плеер реально заиграл: при опросе раз
        в секунду начало фразы уходило бы в распознаватель. Хвост
        `voice_tail_s` не даёт шлюзу щёлкнуть между блоками одной фразы.
        """
        with self._lock:
            self._voice = max(0, self._voice + (1 if active else -1))
            if not active:
                self._voice_until = time.monotonic() + self._tail_s
            self._apply()

    def _playing(self) -> bool:
        """Идёт ли наша озвучка (или ещё не истёк хвост после неё)."""
        return self._voice > 0 or time.monotonic() < self._voice_until

    def _apply(self) -> bool:
        """Вердикт по кэшу опроса и пушу озвучки; вызывается под `self._lock`."""
        return self._set(self._loud and (self._media or self._playing()))

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
        who = "говорю сам" if self._playing() else "играет медиа"
        return (f"Запись заглушена: {who}, а звук идёт не через "
                f"«{self.allowed}»")


def build_record_gate(matcher: Any, output: Any,
                      voice: Any = None) -> Optional[RecordGate]:
    """Собирает шлюз по секции `record_gate` commands.json (не запуская поток).

    Ключи секции: enabled, allowed_device (подстрока имени «тихого»
    устройства), poll_s, min_peak (ниже какого порога пик-метра сессия тишина),
    voice_tail_s (хвост после нашей озвучки), ignored_processes (чей звук не
    считать медиа); чего нет — берём из lib.core.tuning. None — секция
    выключена. `voice` (TextToSpeech) подписывается на переключения шлюза:
    своя озвучка глохнет мгновенно, без лага опроса.
    Поток опросов запускает владелец цикла захвата (worker.run).
    """
    config = matcher.get_record_gate_config()
    if not config.get("enabled"):
        return None
    allowed = str(config.get("allowed_device", RECORD_GATE_ALLOWED_DEVICE))
    poll_s = float(config.get("poll_s", RECORD_GATE_POLL_S))
    min_peak = float(config.get("min_peak", RECORD_GATE_MIN_PEAK))
    tail_s = float(config.get("voice_tail_s", RECORD_GATE_VOICE_TAIL_S))
    ignored = tuple(str(p).lower() for p in
                    config.get("ignored_processes",
                               RECORD_GATE_IGNORED_PROCESSES))
    output.print_info(
        f"[RecordGate] Микрофон глохнет при звуке вне «{allowed}» "
        f"(опрос {poll_s:.1f} с)")
    gate = RecordGate(
        allowed_device=allowed, output=output, poll_s=poll_s,
        media_playing=lambda: media_is_playing(ignored, min_peak),
        voice_tail_s=tail_s)
    if voice is not None:
        voice.set_voice_listener(gate.voice)
    return gate
