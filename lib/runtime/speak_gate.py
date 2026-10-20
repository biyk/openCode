# TOOLTIP: Шлюз озвучки: вслух говорим только когда звук идёт в наушники
"""Правило: озвучивать можно лишь пока вывод идёт на «тихое» устройство
(наушники); всё остальное время — молчаливый режим.

Смысл тот же, что у шлюза захвата (§4.6), только с другой стороны: с колонок
голос ассистента слышен всем и лезет в микрофон, а пользователю без наушников
он бесполезен — фразы он всё равно не различает. Молчит только звук: консоль,
лог и Telegram продолжают писать, поэтому ответы на запросы из чата (§4.7) и
CLI-итоги не теряются.

Решает устройство воспроизведения по умолчанию, а не список входов: при разрыве
BT-связи Windows переключает вывод на колонки сразу, тогда как «есть в списке»
про подключение ничего не говорит (§4.11, `mic_devices.headset_active`).

Сбой проверки (не Windows, COM молчит, токен не задан) — **говорим** (fail-open):
промолчать зря хуже, чем лишить голоса весь дом из-за догадки.
"""
import json
import socket
import time
from typing import Any, Callable, Optional

from lib.core.errors import swallowed
from lib.core.tuning import RECORD_GATE_ALLOWED_DEVICE
from lib.monitor import registry
from lib.runtime.mic_devices import headset_active
from lib.voice_cmd.config_loader import get_device_commands_path

# Подстрока имени «тихого» устройства (регистр не важен). Переопределяется
# speak_gate.headphone_device; за неимением берётся record_gate.allowed_device.
SPEAK_GATE_HEADPHONE_DEVICE = RECORD_GATE_ALLOWED_DEVICE

# Сколько секунд держать вердикт: фразы идут пачками, а COM-опрос — не
# бесплатный; заодно решение по фразе не меняется у неё на середине.
# Переопределяется: speak_gate.ttl_s (в `tuning.py` места нет — тот на лимите).
SPEAK_GATE_TTL_S = 2.0


def console(output: Any, text: str) -> None:
    """Строка в output процесса (он же лог); без него — прямо в консоль."""
    if output is not None:
        output.print_info(text)
    else:
        print(text)


class SpeakGate:
    """Можно ли сейчас говорить вслух: наушники на выводе — да, иначе тихо."""

    def __init__(self, headphone: str, output: Any = None,
                 ttl_s: float = SPEAK_GATE_TTL_S,
                 active: Optional[Callable[[str], Optional[bool]]] = None
                 ) -> None:
        self.headphone = (headphone or "").strip()
        self._output = output
        self._ttl_s = ttl_s
        # Привязка поздняя: тесты подменяют `headset_active` модуля, и уже
        # собранный шлюз обязан взять подмену, а не запомненную ссылку.
        self._active = active or (lambda token: headset_active(token))
        # Вердикта ещё нет: говорим (fail-open), но первый же allowed()
        # обязан доложить состояние в реестр — иначе строка шлюза так и не
        # появилась бы в панели, пока наушники не переключатся.
        self._allowed: Optional[bool] = None
        self._until = 0.0

    def allowed(self) -> bool:
        """True — озвучку играть; False — молчаливый режим (текст пишется)."""
        if not self.headphone:
            return True           # токен не задан: ограничивать не на что
        now = time.monotonic()
        if now < self._until:
            return bool(self._allowed)
        self._until = now + self._ttl_s
        try:
            heard = self._active(self.headphone)
        except Exception as error:                # проверка не цена озвучке
            heard = swallowed("speak_gate.probe", error, None)
        # None — не известно (не Windows, сбой COM): говорим как раньше.
        return self._set(True if heard is None else heard)

    def _set(self, allowed: bool) -> bool:
        """Применяет вердикт; переход — одна строка и одна запись в реестр."""
        if allowed != self._allowed:
            self._allowed = allowed
            registry.report("speak_gate", "Шлюз озвучки",
                            registry.WORKING if allowed else registry.IDLE,
                            "звук в наушниках" if allowed else "молчим")
            console(self._output, f"[SpeakGate] {self._message(allowed)}")
        return self._allowed

    def _message(self, allowed: bool) -> str:
        """Что написать в консоль при переключении шлюза."""
        if allowed:
            return f"Озвучка включена: звук идёт в «{self.headphone}»"
        return (f"Молчаливый режим: звук не в «{self.headphone}» — говорим "
                f"только в консоль, лог и Telegram")


def _sections(matcher: Any = None) -> dict:
    """Секции speak_gate/record_gate/mic: из матчера или прямо из commands.json.

    Матчер есть только в живом процессе ассистента; CLI-озвучки
    (`python -m lib.tts`, крон, скиллы) читают файл устройства сами — иначе
    молчаливый режим действовал бы лишь в одном месте из многих.
    """
    if matcher is not None:
        return {"speak_gate": matcher.get_speak_gate_config(),
                "record_gate": matcher.get_record_gate_config(),
                "mic": matcher.get_mic_config()}
    try:
        with open(get_device_commands_path(socket.gethostname()),
                  encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as error:            # нет конфига — нет ограничения
        return swallowed("speak_gate.config", error, {})
    return {name: data.get(name, {})
            for name in ("speak_gate", "record_gate", "mic")}


def build_speak_gate(matcher: Any = None,
                     output: Any = None) -> Optional[SpeakGate]:
    """Собирает шлюз по секции `speak_gate` commands.json; None — шлюза нет.

    Ключи секции: enabled, headphone_device (подстрока имени наушников; по
    умолчанию — `record_gate.allowed_device`, затем `mic.headphone_device`),
    ttl_s. Выключенная секция или пустой токен = None: озвучка работает как
    прежде, молчаливый режим включается только явно.
    """
    sections = _sections(matcher)
    config = sections.get("speak_gate") or {}
    if not config.get("enabled"):
        registry.report("speak_gate", "Шлюз озвучки", registry.DISABLED,
                        "секция speak_gate выключена")
        return None
    headphone = str(config.get("headphone_device")
                    or (sections.get("record_gate") or {}).get("allowed_device")
                    or (sections.get("mic") or {}).get("headphone_device")
                    or SPEAK_GATE_HEADPHONE_DEVICE)
    gate = SpeakGate(headphone, output=output,
                     ttl_s=float(config.get("ttl_s", SPEAK_GATE_TTL_S)))
    registry.report("speak_gate", "Шлюз озвучки", registry.IDLE,
                    "ждёт первой фразы")
    console(output, f"[SpeakGate] Озвучка только в наушниках «{headphone}»")
    return gate
