# Voice Control

Голосовое управление компьютером через STT (Vosk) и LLM (OpenRouter).

## Установка

```bash
# Клонирование и создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
.\venv\Scripts\activate  # Windows

# Установка Python зависимостей
pip install -r requirements.txt

# Системные зависимости
sudo apt install mpg123  # для воспроизведения TTS
```

## Настройка

1. Создайте файл `.env` в корне проекта:
```
OPENROUTER_API_KEY=your_api_key_here
```

2. Настройте голосовые команды в `targets/commands.json`

## Запуск

```bash
python main.py
```

## Команды

- Активация по кодовому слову (по умолчанию: "Алиса")
- Голосовые команды из `targets/commands.json`
- LLM вопросы (если настроен)

## Тесты

```bash
pytest tests/ -v
```

## Структура

```
voice/
├── main.py           # Точка входа
├── targets/          # Файлы конфигурации команд
│   └── commands.json # Голосовые команды
├── .env              # API ключи
├── lib/
│   ├── commands.py   # Сопоставление команд
│   ├── tts.py        # Синтез речи
│   ├── openrouter.py # LLM клиент
│   └── logger.py     # Логирование
├── prompts/          # Промпты для LLM
└── tests/            # Тесты
```
