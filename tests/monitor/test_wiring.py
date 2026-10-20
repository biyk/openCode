"""Гард проводки монитора: каждый фоновый сервис обязан докладывать в реестр.

Ловит тихую потерю озвучки статуса: без `registry.report(...)` сервис просто
не появится в GUI (или зависнет в прошлом состоянии), а тесты GREEN это не
заметят. Здесь — проверка исходников (текст файла), а не поведения: дешёво и
без живых потоков. Поведение потоков покрыто их собственными тестами.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# id сервиса → модуль, который обязан о нём докладывать
EXPECTED = {
    "stt": "lib/stt/transcription_worker.py",
    "record_gate": "lib/runtime/record_gate.py",
    "speak_gate": "lib/runtime/speak_gate.py",
    "status_poll": "lib/runtime/status_poll.py",
    "cron": "lib/scheduling/cron.py",
    "task_monitor": "lib/core/task_monitor.py",
    "telegram": "lib/telegram/bot.py",
    "version": "lib/versioning/version_checker.py",
    "opencode": "lib/core/orchestrator_opencode.py",
    "llm_bg": "lib/core/orchestrator_llm_bg.py",
}


def _source(relpath: str) -> str:
    return (REPO / relpath).read_text(encoding="utf-8")


def test_every_service_reports_its_id():
    for service_id, relpath in EXPECTED.items():
        text = _source(relpath)
        pattern = r'registry\.report\(\s*"{}"'.format(re.escape(service_id))
        assert re.search(pattern, text), (
            f"{relpath}: не докладывает в реестр про «{service_id}» — "
            f"в GUI сервис исчезнет или заложит старое состояние")


def test_report_helper_is_imported_in_each_service():
    for relpath in EXPECTED.values():
        text = _source(relpath)
        assert "from lib.monitor import registry" in text, (
            f"{relpath}: нет импорта реестра")


def test_main_starts_and_stops_monitor():
    text = _source("main.py")
    assert "start_monitor(" in text, "main.py не поднимает монитор"
    assert re.search(r"monitor\.stop\(\)", text), (
        "main.py не останавливает heartbeat-поток при выходе")


def test_heartbeat_path_is_gitignored():
    """heartbeat — runtime-мусор рядом с command_stats.json (в git не должен)."""
    ignore = _source(".gitignore")
    assert "services_heartbeat.json" in ignore


def test_device_config_documents_monitor_section():
    """Секция monitor в конфиге устройства: дефолты есть, но настройки —
    в живом конфиге, иначе «почему не открылось окно» ищется вслепую."""
    import json

    for path in sorted((REPO / "targets").glob("*/commands.json")):
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        section = data.get("monitor")
        if section is None:
            continue
        assert isinstance(section.get("enabled"), bool)
        assert int(section.get("board_port", 0)) > 0
        assert int(section.get("omni_hang_fails", 1)) >= 1
        assert "omni_cooldown_s" not in section, (
            "фиксированный cooldown вернулся: он и был периодом перезапусков "
            "187–202 с; теперь бэк-офф растёт (omni_backoff_s) + бюджет")
        if "omni_hang_after_s" in section:
            # окно молчания обязана переживать «N неудач подряд» (правило 3),
            # иначе «завис» снова решается раньше, чем успевает догореть запрос
            window = int(section["omni_hang_after_s"])
            assert window >= int(section.get("omni_interval_s", 30)) \
                * int(section.get("omni_hang_fails", 3))
        if "omni_backoff_s" in section:
            assert [float(x) for x in section["omni_backoff_s"]]
        assert "port" not in section, (
            "панель больше не отдельный сервер: ключ `port` (8766) устарел, "
            "вкладка живёт на доске знаний (`board_port`)")


def test_watchdog_reports_omniroute_into_registry():
    """Смотритель — единственный писатель строки «omniroute» в heartbeat:
    без доклада в реестр сервис не попадёт в панель вообще."""
    text = _source("lib/monitor/watchdog.py")
    assert 'SERVICE_ID = "omniroute"' in text
    assert re.search(r"self\._registry\.report\(", text), (
        "watchdog.py не докладывает в реестр — строки не будет в панели")
    assert "_restart" in text and "restart" in _source("lib/monitor/omni.py")


def test_omni_restart_uses_flags_the_cli_has():
    """Регресс «смотритель не может поднять OmniRouter»: у команды
    `omniroute restart` опции --daemon НЕТ (Commander отсекает неизвестный
    флаг с rc=1), а без неё restart поднимает сервер в foreground того же
    процесса и никогда не возвращается. Отсоединённый старт умеет только
    `serve --daemon` — поэтому в omni.py обязан звать stop + serve --daemon."""
    text = _source("lib/monitor/omni.py")
    assert '"serve", "--daemon"' in text
    assert '["stop"]' in text
    assert '"restart", "--daemon"' not in text, (
        "снова зовём несуществующий `restart --daemon` — CLI ответит "
        "«unknown option», и прокси не поднимется никогда")


def test_watchdog_gives_the_server_time_to_warm_up():
    """Регресс «смотритель сам ломает прокси»: порт после `serve --daemon`
    занят с первой секунды, а /healthz отвечает только через ~45 с. Без
    паузы на прогрев такты объявляли греющийся сервер «зависшим»,
    и рестарт гонялся по кругу, не давая прокси дожить до готовности."""
    text = _source("lib/monitor/watchdog.py")
    warmup = text.index("_warmup_left()")
    fails = text.index("self._fails += 1")
    assert warmup < fails, (
        "watchdog.py снова считает неудачи до паузы на подъём сервера")
    assert "MONITOR_OMNI_WARMUP_S" in text


def test_watchdog_never_kills_a_busy_or_unmeasured_gateway():
    """Регресс трёхминутного цикла: молчание пробы — НЕ повод убивать.
    Штатный long-запрос глушит /healthz на минуты (замер: 40–170 с), поэтому
    «завис» решается только по долгому молчанию И нулю соединений; не смогли
    посчитать соединения — тоже не убиваем (destructive только по факту)."""
    text = _source("lib/monitor/watchdog.py")
    kill = text.index('self._restart("завис"')
    assert text.index('return "busy"') < kill, (
        "проверка занятости ушла из-под удара — стримы снова режутся")
    assert text.index('return "unknown"') < kill, (
        "непосчитанные соединения перестали запрещать перезапуск")
    assert "hang_after" in text and "_hang_expired" in text


def test_restart_cadence_is_backoff_and_budget_not_cooldown():
    """Фиксированный cooldown давал ровно период 187–202 с из отчёта
    тестировщика; ему на смену — растущий бэк-офф и бюджет перезапусков."""
    text = _source("lib/monitor/watchdog.py")
    assert "wait_s()" in text and "exhausted()" in text
    assert "MONITOR_OMNI_COOLDOWN_S" not in _source("lib/monitor/tuning.py")
    tuning = _source("lib/monitor/tuning.py")
    assert "MONITOR_OMNI_BACKOFF_S" in tuning
    assert "MONITOR_OMNI_BUDGET_RESTARTS" in tuning


def test_watchdog_sees_the_process_from_outside():
    """pid-файл и соединения — у «завис» должно быть доказательство, а не
    догадка по одной пробе: без omni_proc смотритель слеп (правила 1 и 8)."""
    text = _source("lib/monitor/watchdog.py")
    assert "omni_proc" in text
    proc = _source("lib/monitor/omni_proc.py")
    assert "netstat" in proc and "server_running" in proc


def test_board_server_serves_monitor_tab():
    """Панель живёт на сервере доски: без `/api/monitor` и `install()`
    вкладка осталась бы пустой."""
    text = _source("lib/voice_cmd/knowledge_review_server.py")
    assert "/api/monitor" in text
    assert "monitor_tab(page())" in text
    assert "from lib.monitor.status import collect" in text


def test_dashboard_server_is_gone():
    """Дублирующая сущность удалена: отдельного процесса-дашборда нет."""
    assert not (REPO / "lib" / "monitor" / "dashboard.py").exists()
    assert not (REPO / "tests" / "monitor" / "test_dashboard.py").exists()
