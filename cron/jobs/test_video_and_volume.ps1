# Включает тестовый ролик YouTube в CDP-браузере и выставляет громкость 50%.
python -m lib.browser_control open-url "https://www.youtube.com/watch?v=y65necIJU2Y"
powershell -NoProfile -ExecutionPolicy Bypass -File bin/get_volume.ps1 -Set 70
