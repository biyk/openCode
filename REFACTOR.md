# ПЛАН РЕФАКТОРИНГА

## ТЕКУЩЕЕ СОСТОЯНИЕ

### Основные файлы, превышающие 200 строк

**lib/browser_control.py**: 423 строки (было 667 строк после последних изменений)
**lib/orchestrator.py**: 404 строки (без изменений)
**tests/test_browser_control.py**: 295 строки (без изменений)

Другие крупные файлы:
- tests/test_commands.py: 667 строк
- tests/test_orchestrator.py: 666 строк
- tests/test_tts.py: 520 строк
- tests/test_main.py: 472 строки

### Основные компоненты в lib/browser_control.py (423 строки)

#### 1. HTTP/CDP утилиты (около 40 строк)
- `_http_request()`
- `is_running()`
- `_list_tabs()`

#### 2. Запуск браузера (около 50 строк)
- `_find_browser_exe()`
- `ensure_browser()`
- `_profile_dir()`

#### 3. Работа с вкладками (около 70 строк)
- `open_url()`
- `_activate()`
- `_ws_for()`
- `wait_for_tab()`

#### 4. YouTube утилиты (около 100 строк)
- `youtube_search()`
- `youtube_play()`
- `youtube_open_first()`

#### 5. YouTube вспомогательные функции (около 70 строк)
- `_youtube_is_watch()`
- `_youtube_resume_current()`
- `_youtube_wait_and_open_first()`
- `_youtube_page_tabs()`

#### 6. CLI диспетчер (около 60 строк)
- `_cmd_status()`
- `_cmd_tabs()`
- `_cmd_open_url()`
- `_cmd_eval()`
- `_cmd_click()`
- `_cmd_youtube_play()`
- `main()`

### Основные компоненты в lib/orchestrator.py (404 строки)

#### 1. Класс Orchestrator (основная логика)
- Свойства: dev_mode, speaking, abort_playback, suppress_until
- Методы: process_text, maybe_abort, run_opencode
- Состояние: _window, _opencode_queue, _opencode_worker

#### 2. Текстовая обработка
- Станочная обработка с удалением эха
- Интеграция с TTS и отмена воспроизведения

#### 3. Интеграция с внешними компонентами
- Алиасы (AliasStore)
- Командный матчер (CommandMatcher)
- Выполнитель OpenCode (OpenCodeCliRunner)

### Основные компоненты в tests/test_browser_control.py (295 строк)

#### 1. Тесты CDP/HTTP (около 80 строк)
- test_http_get
- test_http_post_sends_json

#### 2. Тесты работы с вкладками (около 80 строк)
- test_list_tabs
- test_find_tab
- test_open_url_called
- test_open_url_switches_to_existing

#### 3. YouTube тесты (около 120 строк)
- test_youtube_search
- test_youtube_play
- test_youtube_play_no_tab
- test_youtube_open_first_success
- test_youtube_open_first_no_link
- test_youtube_open_first_no_tab

#### 4. Тесты CLI (около 15 строк)
- test_main_unknown
- test_main_status_ok
- test_main_open_url

## ЦЕЛЬ

Сделать каждый основной файл проекта **≤ 200 строк** (≈ 10 страниц кода) для лучшей читаемости, тестирования и поддержки.

## СТРАТЕГИЯ РЕФАКТОРИНГА

### ФАЗА 1: ИЗВЛЕЧЕНИЕ

#### 1. lib/browser_control.py → Разделение на три модуля

**lib/cdp_client.py (120-150 строк)**
- `_http_request()`
- `is_running()`
- `_list_tabs()`
- `_activate()`
- `_ws_for()`
- `wait_for_tab()`
- Утилиты CDP и работа с вкладками

**lib/youtube_browser.py (80-120 строк)**
- `_YOUTUBE_SELECTORS`
- `_YOUTUBE_FIRST_VIDEO_SCRIPT`
- `_YOUTUBE_RESUME_SCRIPT`
- `_youtube_is_watch()`
- `_youtube_resume_current()`
- `_youtube_wait_and_open_first()`
- `_youtube_page_tabs()`
- Основные YouTube-специфические функции

**lib/browser_control.py (оставшиеся ~150-170 строк)**
- `_find_browser_exe()`
- `ensure_browser()`
- `_profile_dir()`
- `open_url()`
- `youtube_search()`
- `youtube_play()`
- `youtube_open_first()`
- CLI диспетчер (`_cmd_*`)
- `main()`

#### 2. lib/orchestrator.py → Разделение на три модуля

**lib/command_processor.py (150-200 строк)**
- Основная логика класса Orchestrator
- `process_text()`
- `maybe_abort()`
- Управление состояние

**lib/state_manager.py (80-120 строк)**
- `_window` (COMMAND_WINDOW_SIZE)
- `_opencode_queue`
- `_opencode_worker`
- `_opencode_active`
- Свойства: dev_mode, speaking, abort_playback, suppress_until

**lib/orchestrator.py (оставшиеся ~100-150 строк)**
- `__init__()` и базовая инициализация
- Вводная документация и константы
- Внешняя интеграция (Aliases, CommandMatcher, TTS, intent, opencode)

#### 3. tests/test_browser_control.py → Разделение на три модуля

**tests/test_cdp_client.py (120-150 строк)**
- HTTP/CDP тесты
- test_http_get
- test_http_post_sends_json
- Тесты CDP клиентов

**tests/test_youtube_browser.py (100-130 строк)**
- Все YouTube тесты
- test_youtube_search
- test_youtube_play
- test_youtube_play_no_tab
- Все test_youtube_open_first_*

**tests/test_browser_control_cli.py (50-80 строк)**
- Тесты CLI
- test_main_unknown
- test_main_status_ok
- test_main_open_url
- test_main_eval
- test_main_click
- test_main_youtube_play

### ФАЗА 2: РЕФАКТОРИНГ

#### 1. Упрощение модулей
- Разделение больших функций на более мелкие, эффективные
- Улучшение именования и документации
- Удаление дублирующего кода
- Обеспечение чистого интерфейса между модулями

#### 2. Согласование изменений
- Обновление всех импортов
- Обновление тестов
- Обновление документации
- Обновление REFACTOR.md

#### 3. Обеспечение работоспособности
- Запуск полного набора тестов
- Проверка lint (flake8, pytest)
- Проверка CLI
- Проверка интеграции с orchestrator

### ФАЗА 3: ВАЛИДАЦИЯ

#### 1. Запуск тестов
```bash
python -m pytest tests/ -q
flake8 --max-line-length=100 lib/*.py tests/*.py
```

#### 2. Проверка CLI
```bash
python -m lib.browser_control status
tabs
youtube-first
```

#### 3. Проверка интеграции
- Запуск orchestrator
- Проверка голосовой команды openyoutube
- Проверка YouTube playback

## ОСНОВНЫЕ СОГЛАСОВАНИЯ

### 1. Управление зависимостями
- Строгое управление импортами между модулями
- Переключение на `from lib.cdp_client import ...` вместо `from lib.browser_control import ...`
- Избегание циклических зависимостей

### 2. Обеспечение работоспособности
- Обеспечение того, что публичный API каждого модуля остается стабильным
- Обновление всех тестов с использованием новых путей импорта
- Обновление документации модулей

### 3. Производительность
- Сохранение всех существующих функций
- Обеспечение того, чтобы рефакторинг не привело к ухудшению производительности
- Минимизация изменений в поведении

### 4. Тестирование
- Обновление всех тестов с использованием новых путей импорта
- Добавление тестов для новых функций (если таковые имеются)
- Обеспечение покрытия тестами

## МЕТОДИКА

### 1. Приоритизация
1. Выполнить refactoring lib/browser_control.py (самый большой файл)
2. Выполнить refactoring lib/orchestrator.py
3. Выполнить refactoring tests/test_browser_control.py

### 2. Итеративный подход
- Реализовывать поэтапно
- После каждого этапа запускать тесты
- Исправлять ошибки на каждом шаге

### 3. Проверка
- Использовать `git diff` для отслеживания изменений
- Использовать GitHub Actions для CI/CD
- Использовать автоматические проверяющие скрипты

## РЕСУРСЫ

### 1. Инструменты
- `pytest` для тестирования
- `flake8` для linting
- `black` для форматирования (если решим его использовать)

### 2. Документация
- README.md
- STRUCTURE.md (описание файлов)
- COMMANDS.md (описание команд)

### 3. Скрипты
- scripts/check_tooltips.py
- scripts/bump_version.py
- scripts/generate_commands_md.py
- scripts/generate_structure.py

## РЕЗЮМЕ

Цель этого refactoring — сделать основные файлы проекта компактнее и более поддерживаемыми:

1. **lib/browser_control.py**: Разделение на CDP клиент, YouTube браузер и CLI диспетчер
2. **lib/orchestrator.py**: Разделение на command processor, state manager и основной orchestrator
3. **tests/test_browser_control.py**: Разделение на CDP тесты, YouTube тесты и CLI тесты

Каждый новый файл будет ~200 строк или меньше, что улучшит читаемость, тестирование и поддержку.

## СЛЕДУЮЩИЕ ШАГИ

1. **Phase 1 - Извлечение**: Создать новые модули
2. **Phase 2 - Refactoring**: Упростить и оптимизировать код
3. **Phase 3 - Validation**: Запустить все тесты и убедиться в работоспособности
4. **Обновление документации**: Обновить README, STRUCTURE.md, COMMANDS.md

---

**Примечание**: Этот план может быть изменен по мере реализации. Обновляйте REFACTOR.md по мере прогресса.