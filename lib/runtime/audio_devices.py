# TOOLTIP: Core Audio: устройство воспроизведения по умолчанию и играющие процессы
"""Что за звук сейчас и кто на нём играет (WASAPI, без pywin32).

Два вопроса, на которые умеет отвечать только Core Audio: как зовётся эндпоинт
по умолчанию (наушники или колонки) и какие процессы на нём издают звук прямо
сейчас. Нужно это шлюзу захвата микрофона: с колонок медиа попадает в микрофон,
и ассистент начинает «слышать» чужую речь.

Плюсы в том, что опрос дешёвый и in-process — никаких PowerShell-скриптов,
как в lib/runtime/media.py (там SMTC видит только «системную» медиа-кнопку,
а не факты воспроизведения по устройствам).
"""
import contextlib
import ctypes
from ctypes import wintypes
from typing import Iterator, Optional

from lib.runtime import win_com as w

E_RENDER = 0                        # DATA_FLOW: воспроизведение
ROLE_CONSOLE = 1                    # eConsole — «устройство по умолчанию»
SESSION_MUTED = 3                   # AudioState: поток заглушён, в наушники не уходит

CLSID_MMDEVAPI = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_ENUMERATOR = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_SESSION_MANAGER2 = "77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"
IID_SESSION_CONTROL2 = "BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"
IID_METER = "C02216F6-8C67-4B5B-9D00-D008E73E0064"   # IAudioMeterInformation

# Имя эндпоинта: FriendlyName; у выключенных/невидимых свойства может не быть —
# тогда DeviceDescription, потом имя интерфейса.
NAME_KEYS = (("a45c254e-df1c-4efd-8020-67d146a850e0", 14),
             ("b3f8fa53-0004-438e-9003-51a46e139bfc", 6),
             ("a45c254e-df1c-4efd-8020-67d146a850e0", 2))

# Индексы vtable: IMMDevice 4 OpenPropertyStore; IPropertyStore 5 GetValue;
# IMMDeviceEnumerator 4 GetDefaultAudioEndpoint; IAudioSessionManager2
# 5 GetSessionEnumerator; IAudioSessionEnumerator 3 GetCount / 4 GetSession;
# IAudioSessionControl2 3 GetState / 14 GetProcessId / 15 IsSystemSoundsSession;
# IAudioMeterInformation 3 GetPeakValue (endpointvolume.h).


class PropertyKey(ctypes.Structure):
    _fields_ = [("fmtid", w.GUID), ("pid", wintypes.DWORD)]


class PropVariant(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p1", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


@contextlib.contextmanager
def _default_endpoint() -> Iterator[w.Com]:
    """IMMDevice эндпоинта по умолчанию; COM-ссылки освобождает в любом случае."""
    enum = dev = None
    try:
        enum = w.create_instance(CLSID_MMDEVAPI, IID_ENUMERATOR)
        dev = w.call_out(enum, 4, ctypes.c_int, ctypes.c_int,
                         args=(E_RENDER, ROLE_CONSOLE))
        yield dev
    finally:
        for obj in (dev, enum):
            if obj is not None:
                obj.release()


def _string_at(store: w.Com, key: PropertyKey) -> Optional[str]:
    """Значение свойства строкой (VT_LPWSTR/VT_BSTR); отсутствие — не ошибка."""
    val = PropVariant()
    hr = store.m(5, ctypes.POINTER(PropertyKey), ctypes.POINTER(PropVariant),
                 args=(ctypes.byref(key), ctypes.byref(val)))
    if hr == 0 and val.vt in (8, 31) and val.p1:
        return ctypes.wstring_at(val.p1)
    return None


def _device_name(dev: w.Com) -> Optional[str]:
    """FriendlyName устройства; None, если ни одно из свойств не прочиталось."""
    store = w.call_out(dev, 4, ctypes.c_int, args=(0,))
    try:
        for fmtid, pid in NAME_KEYS:
            key = PropertyKey()
            key.fmtid = w.guid(fmtid)
            key.pid = pid
            name = _string_at(store, key)
            if name:
                return name
        return None
    finally:
        store.release()


def _process_name(pid: int) -> str:
    """Имя процесса (нижний регистр); «pidN», если имя недоступно (чужой PID)."""
    kernel32 = w.WINDLL.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD)
    handle = kernel32.OpenProcess(0x1010, False, pid)   # QUERY_LIMITED_INFORMATION
    if not handle:
        return f"pid{pid}"
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        ok = kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size))
    finally:
        kernel32.CloseHandle(handle)
    return buf.value.rsplit("\\", 1)[-1].lower() if ok else f"pid{pid}"


def is_audible(state: int, system_sounds: bool, peak: Optional[float],
               min_peak: float = 0.0) -> bool:
    """Издаёт ли аудиосессия звук прямо сейчас.

    По AudioState судить нельзя: он говорит лишь про «не пауза/не мьют», в
    тишине остаётся Active (проверено живьём: спящий VLC — state=0, peak=0.0),
    а играющий звук показывает и 0, и 1 (SoundPlayer — state=1 при пике 0.6).
    Поэтому решает пик-метр — это фактические семплы за последний интервал
    измерения, в тишине он ровно 0.0. Заглушённый поток не считается: в
    микрофон он не утекает. `peak is None` — метр не ответил: тоже не считаем
    (fail-open: ассистент, оглохший из-за сломанной проверки, хуже громкого).
    """
    if system_sounds or state == SESSION_MUTED:
        return False
    return peak is not None and peak > min_peak


def _session_process(session: w.Com, min_peak: float = 0.0) -> Optional[str]:
    """Имя процесса сессии, которая именно звучит; None — тишина/мьют/системные."""
    sc = w.query(session, IID_SESSION_CONTROL2) or session
    try:
        meter = w.query(sc, IID_METER)
        try:
            peak = (w.float_out(meter, 3) if meter is not None
                    else w.float_out(sc, 3))
            if not is_audible(w.int_out(sc, 3), sc.m(15) == 0, peak, min_peak):
                return None
        finally:
            if meter is not None:
                meter.release()
        pid = wintypes.DWORD()
        if sc.m(14, ctypes.POINTER(wintypes.DWORD),
                args=(ctypes.byref(pid),)) != 0:
            return None
        return _process_name(pid.value)
    finally:
        if sc is not session:
            sc.release()


def default_device_name() -> Optional[str]:
    """Устройство воспроизведения по умолчанию (None — не Windows или сбой)."""
    if w.WINDLL is None:
        return None
    with _default_endpoint() as dev:
        return _device_name(dev)


def active_session_processes(min_peak: float = 0.0) -> list[str]:
    """Имена процессов, которые сейчас издают звук на дефолтном эндпоинте.

    `min_peak` — порог пик-метра, ниже которого сессия считается тихой. Пустой
    список означает тишину, а не «не проверили»: сессии перечисляются именно
    для текущего устройства вывода. Не дедуплицирован: вкладка = одна сессия.
    """
    if w.WINDLL is None:
        return []
    names: list[str] = []
    with _default_endpoint() as dev:
        mgr = w.activate(dev, IID_SESSION_MANAGER2)
        try:
            enum = w.call_out(mgr, 5)
            try:
                for i in range(w.int_out(enum, 3)):
                    session = w.call_out(enum, 4, ctypes.c_int, args=(i,))
                    try:
                        name = _session_process(session, min_peak)
                    finally:
                        session.release()
                    if name:
                        names.append(name)
            finally:
                enum.release()
        finally:
            mgr.release()
    return names
