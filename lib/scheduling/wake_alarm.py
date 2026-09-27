# TOOLTIP: Разовая задача-будильник WakeToRun в Планировщике Windows (пробуждение из S0/гибернации)
"""Будильник в Планировщике Windows: разовая задача с WakeToRun.

Зачем: внутренний CronScheduler (`lib/scheduling/cron.py`) — обычный
пользовательский процесс, он заморожен в ожидающем режиме S0 и в
гибернации, поэтому утреннее включение ролика может не наступить.
Планировщик Windows будит машину аппаратным RTC-таймером сама ОС
(таймеры пробуждения разрешены: powercfg RTCWAKE=1), после пробуждения
система «прогреется», а её cron успеет запустить wake_video_and_volume.

Команда «я спать» (lib/sleep_event.py) ставит будильник на сейчас+7ч20 —
за 10 минут до сдвигаемого задания cron (+7ч30).

Действие задачи — пустая (`cmd /c exit`): важен именно момент пробуждения.
Регистрация идемпотентна (-Force: старая задача с этим именем заменяется).
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from typing import Optional

# Имя задачи — ASCII: кириллица в аргументах powershell ломает кодировку.
TASK_NAME = "VoiceWakeAlarm"

# -WakeToRun будит из S0/гибернации; -StartWhenAvailable догоняет, если
# момент уже прошёл (например, ПК был выключен); батареи — без ограничений.
_PS_TEMPLATE = (
    "$t = New-ScheduledTaskTrigger -Once -At '{when}'; "
    "$s = New-ScheduledTaskSettingsSet -WakeToRun "
    "-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
    "-StartWhenAvailable; "
    "$a = New-ScheduledTaskAction -Execute cmd.exe -Argument '/c exit'; "
    "Register-ScheduledTask -TaskName " + TASK_NAME + " -Action $a "
    "-Trigger $t -Settings $s -Force | Out-Null"
)


def schedule_wake_alarm(moment: datetime,
                        timeout: float = 30.0) -> Optional[str]:
    """Регистрирует разовую задачу-будильник на момент `moment`.

    None — успех; иначе короткая текст-причина отказа (stderr powershell
    или таймаут ожидания) — звонящий обязан её залогировать.
    """
    ps = _PS_TEMPLATE.format(when=moment.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", ps],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"powershell не ответил за {timeout:.0f} с"
    if result.returncode == 0:
        return None
    text = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else f"код выхода {result.returncode}"
