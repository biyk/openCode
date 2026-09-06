# Voice Control

Голосовое управление компьютером через STT (Vosk) и LLM.

## Возможности

- Распознавание речи (Vosk, русский/английский)
- Голосовые команды из `targets/<hostname>/commands.json`
- Вопросы к LLM по кодовому слову «пожалуйста» — ответ озвучивается
- Автоперезагрузка файла команд без рестарта приложения

## Требования

- Python 3.11+
- Микрофон
- Интернет (для загрузки модели Vosk, LLM и TTS)
- **OmniRouter** — локальный OpenAI-совместимый гейтвей на `http://localhost:20128/v1`. Активный LLM-провайдер (`omni`) обращается к нему, поэтому сервер должен быть запущен отдельно.

## Установка

```bash
# Виртуальное окружение
conda create -n voice python=3.11 -y && conda activate voice

# Python-зависимости
pip install -r requirements.txt
```

### Системные зависимости (воспроизведение TTS)

- **Windows**: `mpg123` — скопировать в `bin/mpg/` (main.py сам добавляет его в PATH) или `ffplay` (из ffmpeg). WAV (Piper/SAPI) проигрывается встроенным `System.Media.SoundPlayer`.
- **Ubuntu/Debian**: `sudo apt install mpg123 libportaudio2`
- **macOS**: `brew install mpg123 portaudio`

### Офлайн-модель Piper

```bash
python -m piper.download_voices ru_RU-irina-medium --download-dir models/piper
```

## Настройка

### 1. LLM-провайдер

Активный провайдер задаётся в `providers.json` (поле `"active"`):

```json
{
    "active": "omni"
}
```

Доступные провайдеры (все в `lib/providers/`):

| id         | Требует                    |
|------------|----------------------------|
| `omni`     | запущенный сервер OmniRouter на localhost:20128 |
| `openrouter` | `OPENROUTER_API_KEY` в `.env` |
| `gigachat` | `GIGACHAT_CLIENT_ID`/`SECRET` в `.env` |
| `deepseek` | `DEEPSEEK_API_KEY` в `.env` |
| `gpt4free` | —                          |
| `brave`    | запущенный браузер Brave/Chromium |

### 2. Голосовые команды

Файл `targets/commands.json` (или `targets/<hostname>/commands.json` для конкретной машины). Формат — два блока: шаблоны речи → id команды, и id → shell-строка. ОС-специфичные команды — словарь с ключами `windows`/`linux`/`default`:

```json
{
    "commands": {
        "playpause": {
            "linux": "playerctl play-pause",
            "windows": "powershell -c \"...эмуляция медиа-клавиши...\"",
            "default": "playerctl play-pause"
        }
    },
    "match": {
        "playpause": ["пауза", "плей", "дальше", "play", "pause"]
    },
    "llm": {
        "history_limit": 10
    }
}
```

Совпадение ищется как подстрока в распознанном тексте. Ключ `llm.history_limit` задаёт глубину истории диалога (читается в main.py:99).

### 3. Кодовое слово для LLM

LLM активируется словом **«пожалуйста»** в реплике. Оно захардкожено в `main.py:31` (`LLM_TRIGGER`) — через конфиг не меняется.

## Запуск

```bash
python main.py
```

1. Скачает/загрузит модель Vosk (~50 МБ)
2. Начнёт слушать микрофон
3. Распознанное слово-команда → выполнение; реплика с «пожалуйста» → LLM → озвучка (gTTS)
4. Enter для остановки

TTS озвучка — каскад на каждый блок: **gTTS** (интернет) → локальная нейросеть **Piper** (`models/piper/ru_RU-irina-medium.onnx`) → системный голос Windows **System.Speech** (SAPI5 через `bin/tts_sapi.ps1`). Текст разбивается по знакам препинания, блоки синтезируются параллельно и проигрываются по порядку.

### Автозапуск на Windows

Resurrector (`C:\Users\b5\.config\resurrector\config.toml`) следит за `['Voice Control']` (`python main.py`). Запись `[omniroute]` должна оставаться `enabled=false` — OmniRouter управляется собственным супервизором, второй экземпляр вызывает циклический рестарт (`EADDRINUSE` на порту 20128).

## Тесты

```bash
pytest tests/ -v                       # все
pytest tests/test_commands.py -v       # файл
pytest tests/test_commands.py::test_find_command -v   # конкретный тест
```

## Структура проекта

```
voice/
├── main.py                 # Точка входа: STT → команды/LLM → TTS
├── providers.json          # LLM-провайдеры, активный — "omni"
├── targets/
│   ├── commands.json       # Команды по умолчанию (Linux/playerctl)
│   └── <hostname>/         # Устройство-специфичные команды (напр. FLTP-5i3-16512)
├── lib/
│   ├── commands.py         # CommandMatcher: match/commands, автоперезагрузка
│   ├── config_loader.py    # Выбор целевого commands.json по hostname
│   ├── tts.py              # Синтез речи (gTTS → Piper → SAPI5)
│   ├── logger.py           # Логирование и история диалога
│   ├── output.py           # Вывод в консоль
│   └── providers/          # LLM-провайдеры (BaseLLMClient — в __init__.py)
│       ├── __init__.py     # BaseLLMClient: ask() + name
│       ├── manager.py      # ProviderManager
│       ├── omni.py         # OmniRouterClient (активный)
│       ├── openrouter.py
│       ├── gigachat.py
│       ├── deepseek.py
│       ├── gpt4free.py
│       └── brave.py
├── prompts/                # Системный промпт для LLM
├── models/                 # Модели Vosk (скачиваются автоматически)
└── tests/                  # Тесты pytest
```

## Устранение проблем

- **LLM не отвечает**: проверьте, что сервер OmniRouter работает (`http://localhost:20128/v1/chat/completions` отвечает 200). Логи сервера: `~/.omniroute/logs/application/app.log`.
- **Кракозябры в консоли Windows**: норма — консоль в кодировке cp866, это не ошибка приложения.
- **ALSA/PortAudio error (Linux)**: `sudo apt install libportaudio2`.
- **Vosk не скачивается**: проверьте интернет или скачайте вручную с alphacephei.com/vosk/models.