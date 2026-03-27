# Voice Control

Голосовое управление компьютером через STT (Vosk) и LLM (OpenRouter, GigaChat и др.).

## Требования

- Python 3.10+
- Микрофон
- Интернет (для загрузки модели Vosk и работы LLM)
- **Браузер Brave или Chrome/Chromium** (только для провайдера `brave`)

## Установка

### 1. Клонирование репозитория

```bash
git clone <repository_url>
cd voice
```

### 2. Создание виртуального окружения (conda/mamba)

```bash
# Создание окружения
conda create -n voice python=3.11 -y
# или с mamba (быстрее)
mamba create -n voice python=3.11 -y

# Активация
conda activate voice
# или
mamba activate voice
```

### 3. Установка Python зависимостей

```bash
pip install -r requirements.txt
```

### 4. Установка системных зависимостей

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install mpg123 libportaudio2 wmctrl xdotool
```

**macOS:**
```bash
brew install mpg123 portaudio
```

**Windows:**
 mpg123 можно скачать с https://www.mpg123.org/download.shtml

Альтернативный плеер - ffplay (входит в ffmpeg):
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg
```

### 5. Браузер (для провайдера Brave)

**Brave:**
```bash
# Ubuntu/Debian
sudo apt install brave-browser
```

**Chrome:**
```bash
# Ubuntu/Debian
wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo dpkg -i google-chrome-stable_current_amd64.deb
```

**Chromium:**
```bash
# Ubuntu/Debian
sudo apt install chromium-browser
```

## Настройка

### 1. API ключи

Создайте файл `.env` в корне проекта. Какие ключи нужны - зависит от выбранного LLM провайдера в `providers.json`:

```
# OpenRouter (бесплатные модели)
OPENROUTER_API_KEY=sk-or-v1-...

# GigaChat
GIGACHAT_CLIENT_ID=...
GIGACHAT_CLIENT_SECRET=...

# DeepSeek
DEEPSEEK_API_KEY=...
```

### 2. Выбор LLM провайдера

Откройте `providers.json` и измените поле `"active"`:

```json
{
    "active": "openrouter",
    ...
}
```

Доступные провайдеры:
- `openrouter` - OpenRouter (рекомендуется, бесплатные модели)
- `gigachat` - GigaChat (российский)
- `gpt4free` - бесплатные модели без API ключа
- `deepseek` - DeepSeek
- `brave` - ** Brave/Chrome/Chromium** с AI (управление через браузер)

### 3. Голосовые команды

Настройте команды в `targets/commands.json`:
```json
{
    "commands": {
        "открой браузер": "firefox",
        "выключи компьютер": "shutdown now"
    },
    "llm": {
        "enabled": true,
        "trigger": "пожалуйста",
        "history_limit": 10
    }
}
```

Для устройства-специфичных команд создайте файл `targets/<hostname>/commands.json`.

### 4. Кодовое слово для LLM

По умолчанию LLM активируется словом "пожалуйста" в голосовой команде. Изменить можно в `targets/commands.json` → `llm.trigger`.

## Запуск

```bash
python main.py
```

Программа:
1. Автоматически скачает модель Vosk для распознавания речи
2. Начнёт слушать микрофон
3. Нажмите Enter для остановки

### Аргументы командной строки

```bash
python main.py --help
```

## Команды

- **Кодовое слово** (по умолчанию: "Алиса") - активирует слушание
- **Голосовые команды** из `targets/commands.json`
- **LLM вопросы** - добавьте "пожалуйста" в вопрос для ответа от AI

## Тесты

```bash
# Все тесты
pytest tests/ -v

# Один тест
pytest tests/test_commands.py -v

# Конкретная функция
pytest tests/test_commands.py::test_find_command -v
```

## Структура проекта

```
voice/
├── main.py                 # Точка входа
├── providers.json          # Конфигурация LLM провайдеров
├── targets/                # Голосовые команды
│   └── commands.json       # Команды по умолчанию
├── lib/
│   ├── commands.py         # Сопоставление и выполнение команд
│   ├── config_loader.py   # Загрузка конфигурации
│   ├── tts.py             # Синтез речи (gTTS)
│   ├── logger.py          # Логирование
│   ├── output.py          # Вывод в консоль
│   └── providers/         # LLM провайдеры
│       ├── manager.py     # Управление провайдерами
│       ├── base.py        # Базовый класс
│       ├── openrouter.py
│       ├── gigachat.py
│       ├── deepseek.py
│       ├── gpt4free.py
│       └── brave.py
├── prompts/               # Системные промпты
├── models/                # Модели Vosk (скачиваются автоматически)
└── tests/                 # Тесты
```

## Устранение проблем

**"ALSA/HOSX/PORTaudio error"**
```bash
# Ubuntu
sudo apt install libportaudio2

# Проверить устройства ввода
python -c "import sounddevice; print(sounddevice.query_devices())"
```

**Vosk модель не скачивается**
Проверьте интернет-соединение или скачайте вручную с https://alphacephei.com/vosk/models

**LLM не отвечает**
1. Проверьте `.env` файл
2. Убедитесь что API ключ валиден
3. Проверьте `providers.json` - активный провайдер должен совпадать с ключом