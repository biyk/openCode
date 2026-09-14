# Voice Control

Голосовое управление компьютером: STT (Vosk) → детерминированное ядро
(команды/статусы/скиллы/алиасы) → LLM → TTS. Запись микрофона не
останавливается даже во время озвучки — её можно прервать стоп-словом.

## Возможности

- Распознавание речи (Vosk, русская модель)
- Дословные голосовые команды из `targets/<hostname>/commands.json`
- База алиасов «коверканье → команда» (`aliases.json`) + голосовое
  обучение: «запомни [X это Y]», «забудь X»
- Составные команды (`sequences`, напр. «включи новости» =
  открыть ютуб + включить первый ролик)
- Статусы системы (`status.json`: vpn/media/browser_youtube, опрос
  каждые 5 сек) — команды запускаются только при нужных статусах
- Управление браузером через CDP (`lib/browser_control.py`: открыть
  вкладку, клик, JS, ютуб-поиск+плей)
- Вопросы к LLM по триггерному слову («пожалуйста» / «алиса») —
  ответ озвучивается; стоп-слова («стоп», «хватит»...) прерывают озвучку
- Гонка провайдеров: OmniRouter + локальный LM Studio, побеждает
  быстрый ответ
- Автоперезагрузка конфигов (команды/статусы/алиасы) без рестарта

## Требования

- Python 3.11+, микрофон
- Интернет (модель Vosk, gTTS, OmniRouter-апстримы)
- **OmniRouter** — локальный OpenAI-совместимый гейтвей на
  `http://localhost:20128/v1` (свой супервизор, запускается отдельно)
- **LM Studio** — локальный сервер (`lms server start`, порт 1234)
  с моделью `liquid/lfm2.5-1.2b` (второй участник гонки)

## Установка

```bash
# Виртуальное окружение
conda create -n voice python=3.11 -y && conda activate voice

# Python-зависимости
pip install -r requirements.txt
pip install flake8 mypy pytest-mock
```

### Системные зависимости (воспроизведение TTS)

- **Windows**: `mpg123` — скопировать в `bin/mpg/` (main.py сам добавляет
  его в PATH) или `ffplay` (из ffmpeg). WAV (Piper/SAPI) проигрывается
  встроенным `System.Media.SoundPlayer`.
- **Ubuntu/Debian**: `sudo apt install mpg123 libportaudio2`
- **macOS**: `brew install mpg123 portaudio`

### Офлайн-модель Piper

```bash
python -m piper.download_voices ru_RU-irina-medium --download-dir models/piper
```

## Настройка

### 1. LLM-провайдер

Активный провайдер задаётся в `providers.json` (поле `"active"`,
сейчас — `"race"`):

```json
{
    "active": "race"
}
```

Доступные провайдеры (все в `lib/providers/`):

| id         | Что это                                              |
|------------|------------------------------------------------------|
| `omni`     | OmniRouter на localhost:20128, модель `auto` (активный) |
| `openrouter` | `OPENROUTER_API_KEY` в `.env`                      |
| `gigachat` | `GIGACHAT_CLIENT_ID`/`SECRET` в `.env`               |
| `deepseek` | `DEEPSEEK_API_KEY` в `.env`                          |
| `gpt4free` | —                                                    |

Для классификации команд (не диалога) гонка использует `classify()`:
пропускает ответы NONE и не пишет в историю диалога.

### 2. Голосовые команды

Файл `targets/commands.json` (или `targets/<hostname>/commands.json`
для конкретной машины). Секции:

```json
{
    "triggers": ["пожалуйста", "алиса"],
    "commands": {
        "playpause": {
            "linux": "playerctl play-pause",
            "windows": "powershell -c \"...эмуляция медиа-клавиши...\"",
            "default": "playerctl play-pause"
        }
    },
    "match": {
        "playpause": ["пауза", "плей", "дальше"]
    },
    "requires": {
        "playpause": ["media_session"]
    },
    "provides": {
        "openyoutube": ["browser_youtube"]
    },
    "sequences": {
        "news": {"steps": ["openyoutube", "youtube_news"]}
    },
    "llm": {
        "history_limit": 10
    }
}
```

- `match` — только русские фразы (Vosk русская модель, английские
  шаблоны удалены осознанно).
- Совпадение — **дословное**: текст без триггеров должен в точности
  равняться шаблону (регистр/ё/пробелы нормализуются). Подстроки
  НЕ считаются.
- `requires` — статусы, без которых команда не запускается (проверка
  в `StatusStore`, `main.py` передаёт его в матчер).
- `provides` — статусы, выставляемые сразу после успеха команды.
- `sequences` — составные команды: шаги по очереди, стоп на первой
  ошибке, каждый шаг проверяет свои `requires`.
- `llm.history_limit` — глубина истории диалога.

### 3. Триггерные слова и порядок обработки

Реплика **без триггера** → только вывод в консоль. С триггером:

1. Дословная команда → запуск (`[Command]`)
2. Алиас из `aliases.json` → запуск (`[Alias]`)
3. LLM-классификатор (`intent`) — ему описываются триггеры, команды,
   статусы и заблокированные кандидаты; коверканья Vosk («ютюб»)
   разбирает он (`[Mini]`)
4. Скилл (`[Skill]`)
5. Обычный диалог с LLM → озвучка

Команда/алиас с невыполненными статусами не запускается: в консоль
`[Blocked]`, голосом — что нужно сделать (`need_message` из
`status.json`).

### 4. Статусы (`targets/<hostname>/status.json`)

```json
{
    "statuses": {
        "vpn": {"checker": "vpn", "interval": 5,
                "need_message": "Включи VPN вручную"},
        "media_session": {"checker": "media_session", "interval": 5,
                "need_message": "Нет медиа для управления"}
    }
}
```

Встроенные проверки: `vpn` (доступен youtube), `media` (что-то играет),
`media_session` (есть сессия хоть на паузе), `browser`/`browser_youtube`
(вкладка через CDP); либо своя shell-команда (`"check"`, exit 0 =
активен, есть per-OS вариант). Опрос в фоне каждые `interval` секунд
(по умолчанию 5), смены печатаются (`[Status] vpn: on`) и обновляют
заголовок окна консоли. Без файла статусов все `requires` пропускаются.

### 5. Алиасы (`targets/<hostname>/aliases.json`)

```json
{
    "aliases": {
        "включи и ютюб": {"command": "openyoutube", "hits": 0,
                           "confirmed": true}
    },
    "pending": {}
}
```

Известные коверканья запускаются мгновенно без LLM. Обучение голосом:
«запомни [X это Y]» / «запомни» (подтвердить последнее) / «забудь X».
Удачные не-дословные резолвы LLM сами падают в `pending`
(`confirmed: false`) и ждут подтверждения.

### 6. Браузер (CDP)

```bash
python -m lib.browser_control status
python -m lib.browser_control tabs
python -m lib.browser_control open-url "https://youtube.com"
python -m lib.browser_control eval "youtube.com" "document.title"
python -m lib.browser_control click "youtube.com" "button.ytp-play-button"
python -m lib.browser_control youtube-play "музыка"
```

Браузер (Chrome/Brave) запускается сам с `--remote-debugging-port=9222`.
Команда `openyoutube` в конфиге вызывает `open-url`.

## Запуск

```bash
python main.py
```

1. Скачает/загрузит модель Vosk (~50 МБ), запустит опрос статусов
2. Начнёт слушать микрофон (запись не останавливается никогда)
3. Реплика с триггером → команда/алиас/LLM → озвучка (TTS);
   без триггера — только вывод в консоль
4. Enter для остановки

TTS — каскад на каждый блок текста: **gTTS** (интернет) → локальная
нейросеть **Piper** (`models/piper/ru_RU-irina-medium.onnx`) →
системный голос Windows **System.Speech** (SAPI5 через
`bin/tts_sapi.ps1`). Текст режется по знакам препинания, блоки
синтезируются параллельно и проигрываются строго по порядку.
Стоп-слова во время озвучки прерывают её (грамматический
распознаватель + сброс буфера).

Логи: консоль кратко, подробности — `logs/ГГГГММДДЧЧММ.log`
(один файл на запуск). Русская Windows-консоль переключается
в UTF-8 (`chcp 65001`) на старте.

### Автозапуск на Windows

Resurrector (`C:\Users\b5\.config\resurrector\config.toml`) следит за
`['Voice Control']` (`python main.py`). Запись `[omniroute]` должна
оставаться `enabled=false` — OmniRouter управляется собственным
супервизором, второй экземпляр вызывает циклический рестарт
(`EADDRINUSE` на порту 20128).

## Тесты

```bash
pytest tests/ -v                                # все (~415)
pytest tests/test_commands.py -v                # файл
pytest tests/test_commands.py::TestCommandMatcher::test_find_literal_exact_match -v
flake8 lib tests --max-line-length=100          # линт
```

Конвенция: тесты в `tests/test_<module>.py`, внешние зависимости
(API, I/O, аудио, сеть) мокаются. Новые модули — сразу с тестами.

## Структура проекта

```
voice/
├── main.py                 # Точка входа: STT → оркестратор → TTS
├── providers.json          # LLM-провайдеры, активный — "race"
├── targets/
│   ├── commands.json       # Команды по умолчанию
│   └── <hostname>/         # Устройство-специфичное:
│       ├── commands.json   #   команды/матчи/requires/sequences
│       ├── status.json     #   статусы и проверки
│       ├── aliases.json    #   база коверканий
│       └── skills/         #   JSON-скиллы
├── lib/
│   ├── orchestrator.py     # Детерминированное ядро решений
│   ├── commands.py         # CommandMatcher: literal/requires/sequences
│   ├── status.py           # StatusStore: опрос статусов в фоне
│   ├── aliases.py          # AliasStore: база соответствий П6.0
│   ├── skills.py           # SkillRegistry: open_url/run_cmd шаги
│   ├── intent.py           # IntentClassifier: LLM-классификация с контекстом
│   ├── browser_control.py  # CDP-управление браузером (CLI)
│   ├── media.py            # is_media_playing/is_media_available
│   ├── config_loader.py    # Выбор commands.json по hostname
│   ├── tts.py              # Синтез речи (gTTS → Piper → SAPI5)
│   ├── logger.py           # Логирование и история диалога
│   ├── output.py           # Вывод в консоль
│   └── providers/          # LLM-провайдеры (BaseLLMClient — в __init__.py)
│       ├── __init__.py     # BaseLLMClient: ask() + name
│       ├── manager.py      # ProviderManager
│       ├── race.py         # RaceClient: omni+lmstudio, ask()/classify()
│       ├── omni.py         # OmniRouterClient
│       ├── lmstudio.py     # LmStudioClient
│       ├── openrouter.py
│       ├── gigachat.py
│       ├── deepseek.py
│       └── gpt4free.py
├── bin/
│   ├── media_state.ps1     # Статус медиа через SMTC (все сессии)
│   └── tts_sapi.ps1        # Озвучка через System.Speech
├── prompts/                # Системный промпт для LLM
├── models/                 # Модели Vosk (скачиваются автоматически)
└── tests/                  # Тесты pytest
```

## Устранение проблем

- **LLM не отвечает**: проверьте OmniRouter (`http://localhost:20128/v1/chat/completions` → 200; логи `~/.omniroute/logs/application/app.log`) и LM Studio (`lms server status`, модель `liquid/lfm2.5-1.2b` загружена).
- **Команда не запускается, в логе `[Blocked]`**: смотрите каких статусов нет (`[Status]` в логе) — выполните условие (напр. включите VPN вручную).
- **Кракозябры в консоли Windows**: норма — консоль в кодировке cp866 до переключения в UTF-8, это не ошибка приложения.
- **ALSA/PortAudio error (Linux)**: `sudo apt install libportaudio2`.
- **Vosk не скачивается**: проверьте интернет или скачайте вручную с alphacephei.com/vosk/models.
