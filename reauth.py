#!/usr/bin/env python3
"""Скрипт для авторизации Google Calendar.

Вызывается при необходимости авторизации. Сначала озвучивает, что нужна авторизация,
затем открывает браузер для согласования.
"""

# Импортируем TTS из библиотеки
# (используется тот же движок, что и в main.py)
from lib.tts import TextToSpeech


def main():
    # Инициализируем TTS (использует gTTS или локальный piper)
    tts = TextToSpeech()

    # 1. Говорит, что нужна авторизация (реальное воспроизведение)
    tts.speak_and_play(
        "Для напоминаний нужна авторизация Google. Подойди к компьютеру. "
        "Откроется браузер, выбери свой аккаунт и разреши доступ."
    )

    # 2. Запускает авторизацию Google Calendar
    # run_local_server с open_browser=True открывает браузер и ждет согласования
    try:
        from lib.google_calendar import GoogleCalendar
        cal = GoogleCalendar()
        cal.authorize()
        print("[OK] Авторизация успешна!")
        print("Напоминания снова работают. Вы можете создавать напоминания.")
    except Exception as e:
        print(f"[FAIL] Авторизация не удалась: {e}")
        print("Попробуйте снова позже или проверьте доступ к Google.")


if __name__ == "__main__":
    main()
