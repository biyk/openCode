# TOOLTIP: Низкоуровневый Windows COM через ctypes: GUID и вызовы по vtable
"""Обёртка vtable для COM-интерфейсов, которых нет в маршаллинге ctypes.

Аудио-интерфейсы WASAPI (IAudioSessionManager2 и далее) невозможно вызвать
через готовых обёрток, поэтому указатель храним как `void*`, а метод достаём
по индексу из vtable. Ошибка в индексе — не исключение, а access violation
всего процесса, так что индексы и IID берутся из заголовков SDK
(um/mmdeviceapi.h, um/audiopolicy.h, блок COBJMACROS), а не на глаз.

Вне Windows модуль безопасен: `WINDLL` равен None, и вызывающая сторона
трактует это как «ничего не проверяем».
"""
import ctypes
from ctypes import wintypes
from typing import Optional

WINDLL = getattr(ctypes, "windll", None)      # None вне Windows
PV = ctypes.c_void_p
LONG = ctypes.c_long
CLSCTX_INPROC_SERVER = 1


class GUID(ctypes.Structure):
    """_GUID в памяти Windows (первые три поля — little-endian)."""

    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]


def guid(text: str) -> GUID:
    """GUID-строка -> GUID; числовые поля разворачиваем big-endian."""
    raw = bytes.fromhex(text.replace("-", ""))
    out = GUID()
    out.Data1 = int.from_bytes(raw[0:4], "big")
    out.Data2 = int.from_bytes(raw[4:6], "big")
    out.Data3 = int.from_bytes(raw[6:8], "big")
    out.Data4 = (ctypes.c_byte * 8)(*raw[8:16])
    return out


def chk(hr: int, what: str) -> None:
    """hr != S_OK -> OSError с кодом (иначе молча пойдём по битым указателям)."""
    if hr != 0:
        raise OSError(f"{what}: hr={hr & 0xffffffff:#010x}")


class Com:
    """COM-указатель; m(index, ...) вызывает метод vtable по индексу."""

    def __init__(self, raw):
        self.raw = raw

    def m(self, index, *argtypes, **kw):
        # указатель -> саму vtable (один deref — это адрес, а не массив методов)
        vtable = ctypes.cast(ctypes.cast(self.raw, ctypes.POINTER(PV))[0],
                             ctypes.POINTER(PV))
        proto = ctypes.WINFUNCTYPE(LONG, PV, *argtypes)
        return proto(vtable[index])(self.raw, *kw.get("args", ()))

    def release(self) -> int:
        """IUnknown::Release — обязателен, иначе демон копит ссылки."""
        return self.m(2)


def wrap(pp) -> Com:
    return Com(pp.value)


def call_out(obj: Com, index: int, *argtypes, args=()) -> Com:
    """Метод, возвращающий COM-указатель через out-параметр."""
    out = PV()
    chk(obj.m(index, *argtypes, ctypes.POINTER(PV),
              args=tuple(args) + (ctypes.byref(out),)), f"vtable #{index}")
    return wrap(out)


def int_out(obj: Com, index: int, args=()) -> int:
    """Метод, возвращающий число через out-параметр (GetCount, GetState)."""
    val = ctypes.c_int()
    chk(obj.m(index, ctypes.POINTER(ctypes.c_int),
              args=tuple(args) + (ctypes.byref(val),)), f"vtable #{index}")
    return val.value


def float_out(obj: Com, index: int) -> Optional[float]:
    """Метод, возвращающий float через out-параметр; None при hr != S_OK.

    Не бросает исключение: отсутствие значения здесь штатный ответ
    (напр. пик-метр недоступен на некоторых устройствах), а не поломка.
    """
    val = ctypes.c_float()
    if obj.m(index, ctypes.POINTER(ctypes.c_float),
             args=(ctypes.byref(val),)) != 0:
        return None
    return val.value


def activate(dev: Com, iid_text: str) -> Com:
    """IMMDevice::Activate (vtable 3) — интерфейс, привязанный к устройству."""
    return call_out(dev, 3, ctypes.POINTER(GUID), ctypes.c_int, PV,
                    args=(ctypes.byref(guid(iid_text)),
                          CLSCTX_INPROC_SERVER, None))


def query(obj: Com, iid_text: str) -> Optional[Com]:
    """IUnknown::QueryInterface (vtable 0); None, если интерфейс не поддержан."""
    out = PV()
    if obj.m(0, ctypes.POINTER(GUID), ctypes.POINTER(PV),
             args=(ctypes.byref(guid(iid_text)), ctypes.byref(out))) != 0:
        return None
    return wrap(out)


def create_instance(clsid: str, iid: str) -> Com:
    """CoCreateInstance для in-proc класса (MMDeviceEnumerator и т.п.)."""
    ole32 = WINDLL.ole32
    ole32.CoCreateInstance.restype = LONG
    pp = PV()
    chk(ole32.CoCreateInstance(ctypes.byref(guid(clsid)), None,
                               CLSCTX_INPROC_SERVER,
                               ctypes.byref(guid(iid)), ctypes.byref(pp)),
        "CoCreateInstance")
    return wrap(pp)


def co_initialize() -> None:
    """CoInitializeEx для текущего потока (повтор вызова безвреден)."""
    if WINDLL is not None:
        WINDLL.ole32.CoInitializeEx(None, 0)
