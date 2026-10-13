# TOOLTIP: Микрофон: вход ноутбука; BT-микрофон гарнитуры — только по явной просьбе
"""Какой микрофон писать и когда циклу захвата пересобирать поток.

Правило: пишем с микрофона ноутбука, а вход гарнитуры — только по явной просьбе
(`mic.headset_mic`). Все её входы живут в профиле Hands-Free, несовместимом со
стерео-медиа: открыли её микрофон — гарнитура ушла в режим разговора и замолчала,
хотя Windows продолжает считать «Наушники (…H30i)» активным выводом.

Раньше вход выбирали один раз при старте (`_pick_mic_device`): поток оставался на
мёртвом входе гарнитуры, а Windows не переводит открытый PortAudio-поток на другое
устройство — Vosk писал тишину. Теперь цель пересчитывается каждые `poll_s` в
потоке цикла захвата (не в аудио-колбэке), и `follow()` отвечает «пора», когда она
сменилась: поток пересобирается, распознаватель сбрасывается, иначе хвост фразы
склеится с началом речи на новом входе. Дефолты секции `mic` держим здесь
(tuning.py на пределе строк). Живая проверка — `python -m lib.stt.mic_stream`.
"""
from __future__ import annotations

import sys
import time
from typing import Any, Callable, List, Optional

import sounddevice as sd

from lib.core.errors import swallowed
from lib.core.tuning import RECORD_GATE_ALLOWED_DEVICE
from lib.runtime.mic_devices import (
    Target, default_input_index, headset_active, input_devices, match_device,
    safe_inputs,
)

# Подстрока имени микрофона ноутбука; не совпало — системный вход (он и есть
# ноутбучный). Звонковые BT-входы отсекает `mic_devices.safe_inputs`.
MIC_LAPTOP_DEVICE = "realtek"
# Как часто (сек) пересчитывать входы: цикл захвата крутится раз в 0.2 с.
MIC_POLL_S = 2.0
# Пауза (сек) после неудачного открытия: устройство в списке, но не открывается.
MIC_RETRY_S = 15.0
DEFAULT_LABEL = "микрофон по умолчанию"


class MicWatcher:
    """Выбор микрофона и поток захвата, следующий за этим выбором.

    Цикл распознавания зовёт `follow()` на каждой итерации: True — вход
    сменился, поток пересобран, распознаватель надо сбросить.
    """

    def __init__(self, headphone: str = "", laptop: str = MIC_LAPTOP_DEVICE,
                 headset_mic: bool = False, poll_s: float = MIC_POLL_S,
                 retry_s: float = MIC_RETRY_S,
                 headset_active: Optional[Callable[[], Optional[bool]]] = None,
                 devices: Optional[Callable[[], List[tuple]]] = None,
                 default_index: Callable[[], Optional[int]] = default_input_index,
                 output: Any = None) -> None:
        self.headphone = (headphone or "").strip().casefold()
        self.laptop = (laptop or "").strip().casefold()
        self.headset_mic = headset_mic
        self._poll_s = poll_s
        self._retry_s = retry_s
        self._headset_active = headset_active
        self._devices = devices or input_devices
        self._default_index = default_index
        self._output = output
        self._in_use: Optional[Target] = None   # вход открытого потока
        self._stream: Any = None
        self._params: tuple = ()                # (callback, sr, blocksize)
        self._next = 0.0                        # когда снова пересчитывать
        self._retry_at = 0.0                    # до когда не повторять провал

    def target(self) -> Target:
        """Нужный вход сейчас; звонковый BT-вход — только если он разрешён."""
        named = safe_inputs(self._devices(), self.headphone, self.headset_mic)
        if self.headset_mic:
            headset = match_device(named, self.headphone)
            if headset is not None and self._active() is not False:
                return headset
        laptop = match_device(named, self.laptop, skip=self.headphone)
        return laptop if laptop is not None else self._system_default(named)

    def _active(self) -> Optional[bool]:
        """Подключены ли наушники; None — данных нет, смену не решаем."""
        if self._headset_active is None:
            return None
        try:
            return self._headset_active()
        except Exception as error:
            return swallowed("mic_stream.headset_active_cb", error, None)

    def _system_default(self, named: List[tuple]) -> Target:
        """Дефолт берём индексом: иначе смену системного входа не увидеть.

        `named` уже безопасные: подключённая гарнитура становится системным
        входом, а по индексу она мимо — берём первый живой.
        """
        index = self._default_index()
        for entry in named:
            if entry[0] == index:
                return entry
        return named[0] if named else (None, DEFAULT_LABEL)

    def open(self, callback, samplerate: int, blocksize: int) -> Target:
        """Первый выбор и открытие потока (возвращает выбранный вход)."""
        self._params = (callback, samplerate, blocksize)
        self._in_use = self.target()
        self._next = time.monotonic() + self._poll_s
        self._announce(self._in_use)
        self._start(self._in_use, *self._params)
        return self._in_use

    def follow(self) -> bool:
        """Пересобрать поток, если цель сменилась (или не открылась)."""
        now = time.monotonic()
        if now < self._next or now < self._retry_at:
            return False
        self._next = now + self._poll_s
        want = self.target()
        if self._stream is not None and want == self._in_use:
            return False
        self.close()
        self._in_use = want
        self._announce(want)
        self._start(want, *self._params)
        return True

    def _start(self, target: Target, callback, samplerate: int, blocksize: int) -> Any:
        """Открывает и запускает вход: `RawInputStream` сам не играет — без
        `start()` захват молчит (в старом коде это делал `with`). Сбой — пауза."""
        try:
            self._stream = sd.RawInputStream(samplerate=samplerate,
                                             blocksize=blocksize, dtype="int16",
                                             channels=1, callback=callback,
                                             device=target[0])
            self._stream.start()
        except Exception as error:
            self._stream = None
            self._retry_at = time.monotonic() + self._retry_s
            if self._output is not None:
                self._output.print_error(
                    f"[Mic] Не открыть «{target[1]}»: {error}")
        return self._stream

    def close(self) -> None:
        """Гасит поток; сбой закрытия не роняет цикл захвата."""
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception as error:
            swallowed("mic_stream.close", error)

    def _announce(self, target: Target) -> None:
        """Одна строка в консоль: каким микрофоном пишем теперь."""
        if self._output is not None:
            self._output.print_info(f"[Mic] Микрофон: {target[1]}")


def build_mic_watcher(matcher: Any, gate: Any = None,
                      output: Any = None) -> MicWatcher:
    """Собирает наблюдитель по секции `mic` (+ `record_gate`) commands.json.

    Токен гарнитуры — у шлюза захвата: в неё течёт звук, её звонковый вход и
    опасен по умолчанию.
    """
    config = matcher.get_mic_config()
    quiet = str(config.get("headphone_device")
                or (gate.allowed if gate is not None
                    else RECORD_GATE_ALLOWED_DEVICE))
    return MicWatcher(headphone=quiet,
                      laptop=str(config.get("laptop_device", MIC_LAPTOP_DEVICE)),
                      headset_mic=bool(config.get("headset_mic", False)),
                      poll_s=float(config.get("poll_s", MIC_POLL_S)),
                      headset_active=lambda: headset_active(quiet), output=output)


def report(watcher: MicWatcher, active: Optional[bool]) -> str:
    """Отчёт для ручной проверки: входы, вывод, вердикт «какой вход нужен»."""
    device, label = watcher.target()
    lines = [f"  [{i}] {n}" for i, n in watcher._devices()]
    return "\n".join([f"Звук идёт в гарнитуру: {active}", "Входы:"] + lines +
                     ["", f"Нужен: {label} (индекс {device})"])


def main() -> int:
    """CLI проверки живьём: `python -m lib.stt.mic_stream`."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    active = headset_active(RECORD_GATE_ALLOWED_DEVICE)
    watcher = MicWatcher(headphone=RECORD_GATE_ALLOWED_DEVICE,
                         headset_active=lambda: active)
    print(report(watcher, active))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
