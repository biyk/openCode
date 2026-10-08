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

from lib.scheduling.cron import CronScheduler  # noqa: E402
from lib.core.output import TranscriptionOutput, TimestampedStream  # noqa: E402
from lib.core.single_instance import AlreadyRunning, acquire  # noqa: E402
from lib.core.task_finish import make_task_finisher  # noqa: E402
from lib.core.task_monitor_launch import start_task_monitor  # noqa: E402
from lib.core.task_pick import make_task_picker  # noqa: E402
from lib.stt.text_inputs import TextInputs, submit_manual_text  # noqa: E402
from lib.stt.transcription_worker import TranscriptionWorker  # noqa: E402
from lib.telegram.launch import start_telegram  # noqa: E402

# ---------- Главная функция ----------


def main():
    from lib.versioning.version_checker import start_version_checker
    from lib.versioning.version_gate import snapshot as _snapshot

    # Single-instance lock ДО всего остального: иначе второй `python main.py`
    # (F5 в IDE, ручной старт в соседней консоли) успевает поднять
    # Vosk-воркер на том же микрофоне, Telegram-поток (Bot API → 409
    # Conflict на getUpdates) и TTS-плеер — команды распознаются дважды,
    # озвучка играет дважды. Сокет держим в локальной переменной до
    # конца main(): когда процесс умрёт (обычный выход/Ctrl+C/kill), ядро
    # ОС само снимет bind.
    try:
        _lock = acquire()  # noqa: F841 — ссылка нужна, чтобы GC не закрыл fd
    except AlreadyRunning as exc:
        print(f"[Startup] {exc}")
        sys.exit(1)

    snap = _snapshot()
    # Проверка перед стартом (быстрый fail)
    from lib.versioning.version_gate import check_versions_or_exit

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

    # Telegram-бот (секция telegram): те же команды текстом из мессенджера,
    # ответы — в чат, без озвучки. Поднимаем до монитора: оповещение о
    # переработке дублируется в чат через bot.broadcast, а нажатие кнопки
    # предложения задачи запускает её через make_task_picker; кнопка
    # «Завершить» (лепится к ответу старта) зовёт make_task_finisher.
    telegram = start_telegram(
        worker, output,
        on_pick=make_task_picker(record=worker._matcher.record_use),
        on_finish=make_task_finisher(record=worker._matcher.record_use))

    # Фоновый контроль таблицы real_life_tasks (секция task_monitor):
    # вопросы вслух, старт задачи по ответу и оповещение о переработке.
    task_monitor = start_task_monitor(
        worker, output,
        notify=telegram.broadcast if telegram is not None else None,
        offer=telegram.offer if telegram is not None else None,
        finish_markup=(telegram.finish_markup if telegram is not None
                       else None))

    output.print_info("\n🎙️  Запись... Команды можно говорить, печатать "
                      "или писать в Telegram.\n")
    TextInputs(lambda t: submit_manual_text(worker, t), output=output).run()

    if telegram is not None:
        telegram.stop()
    if task_monitor is not None:
        task_monitor.stop()
    worker.stop()
    thread.join(timeout=2)
    cron.stop()
    output.print_info("Выход.")


if __name__ == "__main__":
    # Метка времени на каждой строке консоли — и для print_info, и для
    # прямых print() с тегами по всему коду; ставим на весь поток в одном
    # месте (в __main__, чтобы import main не подменял stdout чужому процессу).
    sys.stdout = TimestampedStream(sys.stdout)
    sys.stderr = TimestampedStream(sys.stderr)
    main()
