# TOOLTIP: Скорость играющего видео в тестовом браузере: поиск звучащей вкладки и сдвиг playbackRate
"""Скорость воспроизведения — «алиса быстрее / алиса медленней».

Звучащую вкладку ищем по состоянию самой страницы: CDP в `/json/list` не
отдаёт признак «эта вкладка издаёт звук» (полей audible там нет), поэтому
каждую обычную вкладку спрашиваем JS-пробой по `video`/`audio`. Из играющих
элементов выбирается звучащий (не muted, volume > 0), заглушённые — в конце
списка; найденной вкладке двигаем `playbackRate` на шаг (параметр `step`
команды в commands.json — 0.05, как шаг громкости).

Плееры в iframe (встроенные ролики) пробой не видны: смотрим основной документ.

Запуск:
    python -m lib.browser.playback_rate up 0.05
    python -m lib.browser.playback_rate down 0.05
"""

import json
import sys
from typing import Any, Optional

from lib.browser import cdp_client as cdc
from lib.browser.cdp_client import DEFAULT_PORT

# Границы скорости: ниже 0.25 речь неразборчива, выше 4.0 уже не слушают.
# Шаг живёт не здесь — он числовой параметр команды (`step`), как у
# громкости, и тюнится пер-девайсно в commands.json.
RATE_MIN = 0.25
RATE_MAX = 4.0
# Шаг для ручного запуска из консоли, когда его не указали.
STEP_DEFAULT = 0.05

# Озвучка итога: клиент говорит сам (как lib.shopping / lib.tasks), голосовой
# цикл ничего не добавляет. Сдвиг на 0.05 на слух почти незаметен, поэтому
# подтверждение направления важнее нейтрального «Готово».
PHRASES = {"up": "Быстрее", "down": "Медленней"}
PHRASE_SILENCE = "Ни одно видео не играет"

# Элемент «играет» = не на паузе, не закончен, данные текут (readyState ≥ 2).
_PLAYING = "if (m.paused || m.ended || m.readyState < 2) continue;"
_AUDIBLE = "!m.muted && m.volume > 0"  # звук идёт с этой вкладки


def _probe_js() -> str:
    """JS вопроса «звучит ли страница»: первый играющий элемент и его скорость."""
    return (
        "(function(){'use strict';"
        "var els = document.querySelectorAll('video, audio');"
        "for (var i = 0; i < els.length; i++) {"
        "  var m = els[i];"
        + _PLAYING +
        "  return {playing: true, audible: " + _AUDIBLE + ","
        "          rate: m.playbackRate};"
        "}"
        "return {playing: false, audible: false, rate: 0};"
        "})()"
    )


def _apply_js(delta: float) -> str:
    """JS сдвига скорости всех играющих элементов вкладки на `delta`."""
    return (
        "(function(){'use strict';"
        "var delta = " + json.dumps(delta) + ";"
        "var els = document.querySelectorAll('video, audio');"
        "var before = 0, after = 0, count = 0;"
        "for (var i = 0; i < els.length; i++) {"
        "  var m = els[i];"
        + _PLAYING +
        "  var rate = Math.min(" + str(RATE_MAX) + ", Math.max("
        + str(RATE_MIN) + ", m.playbackRate + delta));"
        "  if (!count) { before = m.playbackRate; after = rate; }"
        "  m.playbackRate = rate;"
        "  count++;"
        "}"
        "return {playing: count > 0, count: count, before: before,"
        "        after: after};"
        "})()"
    )


def _eval(tab: dict, script: str) -> dict:
    """JS на вкладке → словарь; пустой словарь — вкладка не ответила."""
    ok, value = cdc.eval_js(tab, script)
    if not ok:
        return {}
    return value if isinstance(value, dict) else {}


def page_tabs(port: int = DEFAULT_PORT) -> list[dict]:
    """Обычные вкладки: service worker и фоновые страницы расширений — мимо."""
    return [t for t in cdc._list_tabs(port)
            if t.get("type", "page") in ("page", "")]


def sounding_tabs(port: int = DEFAULT_PORT) -> list[tuple[dict, dict]]:
    """Вкладки, где что-то играет: звучащие впереди, заглушённые — после.

    Порядок внутри группы сохраняется (как в списке браузера), поэтому
    повторная команда крутит скорость одной и той же вкладки, а не прыгает.
    """
    found = []
    for tab in page_tabs(port):
        info = _eval(tab, _probe_js())
        if info.get("playing"):
            found.append((tab, info))
    return sorted(found, key=lambda pair: 0 if pair[1].get("audible") else 1)


def bump_rate(delta: float, port: int = DEFAULT_PORT) -> dict:
    """Меняет скорость играющего видео; ok=False — если играть нечему.

    Вкладку не активируем: `playbackRate` применим и к фоновой вкладке, а
    угон фокуса у пользователя ни за что.
    """
    tabs = sounding_tabs(port)
    if not tabs:
        return {"ok": False, "error": "ни одно видео не играет"}
    tab, info = tabs[0]
    res = _eval(tab, _apply_js(delta))
    if not res.get("playing"):
        # Вкладка замолчала между пробой и сдвигом (ролик закончился).
        return {"ok": False, "error": "вкладка перестала играть"}
    return {"ok": True, "title": (tab.get("title") or "").strip(),
            "url": tab.get("url", ""), "before": res.get("before"),
            "after": res.get("after"), "count": res.get("count"),
            "audible": bool(info.get("audible")), "others": len(tabs) - 1}


def _num(value: Any) -> str:
    """Скорость для печати: 1 → «1», 0.95 → «0.95»."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _report(result: dict) -> None:
    """Итог в консоль/лог: какая вкладка и какая стала скорость."""
    if not result.get("ok"):
        print(f"[Browser] {result.get('error')}")
        return
    muted = "" if result.get("audible") else " (без звука)"
    extra = "" if not result.get("others") else \
        f" +{result['others']} играющих вкладок(и)"
    print(f"[Browser] «{result.get('title')}»: скорость "
          f"{_num(result.get('before'))} → {_num(result.get('after'))}"
          f"{muted}{extra}")


def _speak(text: str) -> None:
    """Озвучка итога; TTS лениво (как в shopping), сбой — в печать."""
    from lib.tts import TextToSpeech
    try:
        TextToSpeech().speak_and_play(text)
    except Exception as e:  # озвучка не должна ронять выполненный сдвиг
        print(f"[Voice] Озвучка не удалась: {e}")


def parse_args(argv: list[str]) -> tuple[Optional[str], float]:
    """`up|down [шаг]` → (действие, шаг); неверный ввод → (None, 0).

    Шаг приходит из commands.json (`{{step}}`); запятая как разделитель
    десятичной — от ручного запуска и от LLM-подстановки.
    """
    action = argv[0] if argv else ""
    if action not in PHRASES:
        return None, 0.0
    if len(argv) < 2:
        return action, STEP_DEFAULT
    try:
        step = abs(float(argv[1].replace(",", ".")))
    except ValueError:
        return None, 0.0
    return (action, step) if step > 0 else (None, 0.0)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: `python -m lib.browser.playback_rate up|down [шаг]`. 0 — успех."""
    args = list(sys.argv[1:] if argv is None else argv)
    action, step = parse_args(args)
    if action is None:
        print("usage: python -m lib.browser.playback_rate up|down [шаг]")
        return 2
    result = bump_rate(step if action == "up" else -step)
    _report(result)
    _speak(PHRASES[action] if result.get("ok") else PHRASE_SILENCE)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    from lib.core.output import stamp_stdio
    if sys.platform == "win32":  # консоль может стоять в cp866/cp1251
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception as e:  # не удалось перенастроить — печатаем как есть
            print(f"[Browser] Кодировка консоли не переключена: {e}")
    stamp_stdio()  # у дочернего процесса свой stdout — метки ставим здесь
    raise SystemExit(main())
