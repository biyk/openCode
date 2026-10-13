# TOOLTIP: Записывающие устройства: имена входов и «подключены ли наушники»
"""Что за микрофоны есть и жива ли гарнитура (PortAudio + Core Audio).

Отвечает на два вопроса наблюдателю микрофона (`lib/stt/mic_stream.py`):
какие входы вообще можно открыть и идёт ли звук в гарнитуру сейчас.

Два факта, проверенных живьём на этом ПК, задают дизайн:

* вход отключенной BT-гарнитуры остаётся в перечислении PortAudio —
  `Головной телефон (...bthhfenum...;(soundcore H30i))` висит в списке и с
  выключенными наушниками (как и две другие спаренные гарнитуры). Поэтому
  «есть в списке» не значит «подключена», и решение выносит устройство
  воспроизведения по умолчанию: при разрыве Windows переключает вывод на
  колонки немедленно;
* sounddevice 0.4.7 не отдаёт флаг `available` — полагаться на него нельзя,
  но если версия начнёт его отдавать, мёртвый вход мы уже не выберем.

Третий факт — про цену открытия BT-микрофона: все входы гарнитуры живут в
профиле Hands-Free (HFP/SCO), а он не сосуществует со стерео-медиа (A2DP).
Как только такой вход открыт, гарнитура уходит в режим разговора и молчит,
хотя Windows продолжает считать A2DP-эндпоинт активным и дефолтным — проверить
это по состоянию устройств нельзя, слышно только пользователю. Поэтому такие
входы по умолчанию не открываем (`is_call_input`), а решение о гарнитуре
принимаем по устройству воспроизведения.

Имена BT-эндпоинтов содержат CR/LF внутри (`%0\r\n;(soundcore H30i)`) —
приводим их к одной строке, иначе консоль рвётся на каждой смене входа.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import sounddevice as sd

from lib.core.errors import swallowed
from lib.runtime.audio_devices import default_device_name
from lib.runtime.win_com import co_initialize

# Выбор входа: (индекс PortAudio | None = системный дефолт, имя для людей).
Target = Tuple[Optional[int], str]

# Входы профиля Hands-Free: Windows называет их по-разному по локалям и по
# драйверам (MME/WASAPI), но все они — «звонковый» канал гарнитуры, открыв
# который мы вешаем её стерео-воспроизведение. «headset» сюда не пишем: так
# называются и USB-гарнитуры, у которых конфликта профилей нет.
CALL_INPUT_MARKERS = ("hands-free", "bthhfenum", "головной телефон")


def clean_name(raw: object) -> str:
    """Имя устройства в одну строку (в BT-именах сидят CR/LF)."""
    return " ".join(str(raw or "").split())


def headset_active(quiet: str) -> Optional[bool]:
    """Идёт ли звук в «тихое» устройство (наушники); None — не известно.

    None — это и не-Windows, и сбой COM, и пустой маркер. Без уверенности
    вход не переключаем: потерять ноутбучный микрофон глупой догадкой
    дороже, чем посидеть ещё такт на текущем.
    """
    want = (quiet or "").strip().casefold()
    if not want:
        return None
    try:
        co_initialize()                # COM текущего потока (не аудио-колбэк)
        name = default_device_name()
    except Exception as error:
        return swallowed("mic_devices.headset_active", error, None)
    return None if name is None else want in name.casefold()


def input_devices(devices: Optional[list] = None) -> List[Tuple[int, str]]:
    """Записывающие входы: [(индекс, имя)]. Сбой опроса — пустой список.

    Без каналов записи эндпоинт открыть нельзя; `available` учитываем, если
    версия sounddevice его отдаёт. Исчезнувшую гарнитуру это НЕ ловит —
    для неё есть `headset_active`.
    """
    try:
        rows = sd.query_devices() if devices is None else devices
    except Exception as error:
        return swallowed("mic_devices.input_devices", error, [])
    return [(i, clean_name(d.get("name"))) for i, d in enumerate(rows)
            if d.get("max_input_channels") and d.get("available", True)]


def is_call_input(name: str, token: str = "") -> bool:
    """Звонковый ли это вход: маркеры HFP или имя самой гарнитуры (`token`).

    Токен нужен отдельно: у BT-гарнитуры входов несколько, и имя одного из них
    Windows обрезает до 31 символа — «Головной телефон (soundcore H30», без
    «...H30i» целиком. Маркеры ловят и такой обрезанный вариант.
    """
    low = (name or "").casefold()
    if any(marker in low for marker in CALL_INPUT_MARKERS):
        return True
    want = (token or "").strip().casefold()
    return bool(want) and want in low


def safe_inputs(named: List[Tuple[int, str]], token: str = "",
                allow_call: bool = False) -> List[Tuple[int, str]]:
    """Входы, открытие которых не вешает воспроизведение гарнитуры.

    `allow_call` — пользователь сам решил говорить в BT-микрофон и согласен,
    что медиа в наушниках на это время замолчит. Пустой результат — не «микрофона
    нет», а «фильтровать нечего»: отдаём все входы (fail-open: оглохнуть для
    команд хуже, чем выбрать неудачный вход).
    """
    if allow_call:
        return list(named)
    kept = [t for t in named if not is_call_input(t[1], token)]
    return kept or list(named)


def match_device(named: List[Tuple[int, str]], token: str,
                 skip: str = "") -> Optional[Target]:
    """Первый вход с `token` в имени (регистр не важен); None — такого нет.

    `skip` — подстрока, которую не пускаем в кандидаты: во вход гарнитуры
    попадает и имя адаптера, и ноутбучный токен по нему привёл бы нас
    обратно в мёртвый вход.
    """
    want = (token or "").strip().casefold()
    drop = (skip or "").strip().casefold()
    if not want:
        return None
    for index, name in named:
        low = name.casefold()
        if want in low and not (drop and drop in low):
            return index, name
    return None


def default_input_index() -> Optional[int]:
    """Индекс входа, который система считает своим (None — PortAudio молчит)."""
    try:
        return sd.query_devices(kind="input").get("index")
    except Exception as error:
        return swallowed("mic_devices.default_input", error, None)
