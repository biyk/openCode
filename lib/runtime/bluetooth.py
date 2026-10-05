# TOOLTIP: Диагностика Bluetooth: список устройств Windows и попытка прочитать заряд
"""Список Bluetooth-устройств и уровни их заряда.

Ручная проверка:
    python -m lib.runtime.bluetooth            # человекочитаемый отчёт
    python -m lib.runtime.bluetooth battery     # только про заряд
    python -m lib.runtime.bluetooth --json      # сырой вывод bin/bt_devices.ps1

Заряд Windows отдаёт не для всех устройств. Источник ищется по цепочке
(батарея того же контейнера -> BatteryStatus самого devnode'а -> видимость
GATT Battery Service), и если ничего не подошло, возвращается «неизвестно»,
а не 0: устройство может просто не репортить заряд (так делают почти все
дешёвые TWS-наушники — их процент знает только фирменное приложение).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "bt_devices.ps1"
PS_TIMEOUT_S = 90

# Коды source из bin/bt_devices.ps1 (в скрипте — ASCII, текст живёт здесь).
SOURCE_LABELS = {
    "battery-devnode": "батарея того же контейнера",
    "battery-status": "BatteryStatus самого devnode",
    "gatt-service-visible": "GATT Battery Service виден, процент не отдаётся",
    "none": "нет источника заряда в Windows",
}
UNKNOWN = "неизвестно"


def collect(timeout_s: int = PS_TIMEOUT_S) -> Dict[str, Any]:
    """Собирает данные софта Windows; при любом сбое — dict с ключом error."""
    if os.name != "nt":
        return {"error": "не Windows"}
    if not SCRIPT.exists():
        return {"error": f"нет скрипта {SCRIPT}"}
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(SCRIPT),
    ]
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"powershell: {exc}"}
    out = (res.stdout or "").strip()
    if not out:
        return {"error": (res.stderr or "").strip()[:200] or "пустой вывод"}
    try:
        data = json.loads(out)
    except ValueError as exc:
        return {"error": f"битый JSON: {exc}"}
    if not isinstance(data, dict):
        return {"error": "в ответе не объект"}
    return data


def devices(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Список устройств из собранного словаря (пусто, если данных нет)."""
    found = data.get("devices")
    return list(found) if isinstance(found, list) else []


def battery_text(dev: Dict[str, Any]) -> str:
    """Одна строка про заряд устройства по коду source из PowerShell."""
    batt = dev.get("battery") or {}
    pct = batt.get("percent")
    label = SOURCE_LABELS.get(batt.get("source") or "none", UNKNOWN)
    if isinstance(pct, int):
        state = "на зарядке" if batt.get("charging") else "не на зарядке"
        return f"{pct}% ({state}; {label})"
    return f"{UNKNOWN} ({label})"


def _one_line(dev: Dict[str, Any]) -> str:
    conn = "подключено" if dev.get("connected") else "отключено"
    if dev.get("conn_count") is None:
        conn += " (не известно)"
    profs = ", ".join(dev.get("profiles") or []) or "нет"
    return "  {name} [{mac}] {transport} {conn}\n" \
           "      профили: {profs}\n" \
           "      заряд: {batt}".format(
               name=dev.get("name") or "?",
               mac=dev.get("mac") or "?",
               transport=dev.get("transport") or "?",
               conn=conn,
               profs=profs,
               batt=battery_text(dev),
           )


def _has_percent(dev: Dict[str, Any]) -> bool:
    """Есть ли у устройства измеренный процент (в отличие от «неизвестно»)."""
    return isinstance((dev.get("battery") or {}).get("percent"), int)


def format_report(data: Dict[str, Any], only_battery: bool = False) -> str:
    """Человекочитаемый отчёт (или одна строка причины при сбое сбора)."""
    if data.get("error"):
        return f"Bluetooth недоступен: {data['error']}"
    radios = ", ".join(
        r.get("name") or "?" for r in (data.get("radios") or [])
    ) or "радио не найдено"
    found = devices(data)
    head = f"Bluetooth-устройств: {len(found)} (радио: {radios}, " \
           f"build {data.get('os_build') or '?'})"
    if not found:
        return head + "\n  ни одного спаренного устройства"
    if only_battery:
        measured = [d for d in found if _has_percent(d)]
        if not measured:
            lines = [head, "  процент не известен ни у одного устройства:"]
            lines += [_one_line(d) for d in found]
            return "\n".join(lines)
        return "\n".join([head] + [_one_line(d) for d in measured])
    return "\n".join([head] + [_one_line(d) for d in found])


def main(argv: List[str] | None = None) -> int:
    """CLI диагностики; возвращает 0 даже при недоступном Bluetooth."""
    parser = argparse.ArgumentParser(
        description="Список Bluetooth-устройств и их заряд",
    )
    parser.add_argument(
        "mode", nargs="?", default="list", choices=("list", "battery"),
        help="list — все устройства, battery — только про заряд",
    )
    parser.add_argument(
        "--json", action="store_true", help="сырой вывод PowerShell",
    )
    args = parser.parse_args(argv)
    data = collect()
    if args.json:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        text = format_report(data, only_battery=args.mode == "battery")
    _print(text)
    return 0


def _print(text: str) -> None:
    """Печатает в UTF-8 (описания с юникодом падают на cp866/cp1251)."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    print(text)


if __name__ == "__main__":
    raise SystemExit(main())
