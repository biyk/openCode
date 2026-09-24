import os
import socket
import sys
import threading

# Добавить mpg123 в PATH (Windows)
mpg_path = os.path.join(os.path.dirname(__file__), "bin", "mpg")
if os.path.isdir(mpg_path):
    os.environ["PATH"] = mpg_path + os.pathsep + os.environ.get("PATH", "")

# Исправить кодировку консоли Windows (Vosk возвращает cp866/utf-8 мусор на Windows)
if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from lib.cron import CronScheduler  # noqa: E402
from lib.output import TranscriptionOutput  # noqa: E402
from lib.transcription_worker import TranscriptionWorker  # noqa: E402

# ---------- Главная функция ----------


def main():
    from lib.version_checker import start_version_checker
    from lib.version_gate import snapshot as _snapshot

    snap = _snapshot()
    # Проверка перед стартом (быстрый fail)
    from lib.version_gate import check_versions_or_exit

    check_versions_or_exit(snap.app_version, snap.project_version)

    stop_evt = threading.Event()
    start_version_checker(stop_evt, interval_s=120.0)

    lang = "ru"
    device_name = socket.gethostname()

    output = TranscriptionOutput()
    worker = TranscriptionWorker(lang_code=lang, device_name=device_name,
                                 output=output)

    thread = threading.Thread(target=worker.run, daemon=True)
    thread.start()

    cron = CronScheduler(
        os.path.join(os.path.dirname(__file__), "cron", "crontab.json"),
        output=output,
        base_dir=os.path.dirname(__file__),
    )
    cron.start()

    output.print_info("\n🎙️  Запись... Нажмите Enter для остановки.\n")
    input()

    worker.stop()
    thread.join(timeout=2)
    cron.stop()
    output.print_info("Выход.")


if __name__ == "__main__":
    main()
