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
        assert int(section.get("port", 0)) > 0
