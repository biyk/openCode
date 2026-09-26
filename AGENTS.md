# Voice Control Project - Agent Guidelines

Голосовой ассистент на Windows: Vosk STT → обработка команд → TTS. Речь — это поток строк STT;
разбор команды идёт по правилу «трёх строк» (см. §10), затем — decision-слой Laya, intent, opencode.

## 1. Git commits — ТОЛЬКО ПО ЯВНОЙ КОМАНДЕ
- **Коммитить, пушить, делать PR запрещено без явной команды пользователя.** Сначала показать результат и ждать подтверждения.
- Исключение: авто-коммиты от хуков (`.git/hooks/post-commit` bump-версии) — их создаёт сам хук, агент не инициирует.
- Без команды не вызывать `git commit` / `git push` / `git add`, даже если задача выглядит завершённой.

## 2. Version gate
- `main.py` при старте и в потоке `lib/versioning/version_checker.py` (интервал 120 c) сверяет **app version** (`lib/__init__.py::__version__`) с **project version** (`VERSION`). При несовпадении — жёсткий выход (`os._exit(1)`).
- Если процесс «внезапно выходит» или тесты ломаются — первым делом проверять `lib/versioning/version_gate.py` + `version_checker.py`.
- После bump-коммита `VERSION` и `__version__` синхронны; не рассинхронизировать их вручную.

## 3. Build / Lint / Test Commands (Windows)

```bash
# Все тесты
python -m pytest tests/ -v

# Один файл / один тест
python -m pytest tests/core/test_orchestrator.py -v
python -m pytest tests/core/test_orchestrator.py::TestOrchestratorProcess::test_process_text_command_found -v

# Линейные новые тесты тоже в подпапках-зеркалах: tests/voice_cmd/, tests/runtime/, ...

# Линт — ТОЛЬКО этой командой (совпадает с pre-commit):
flake8 --max-line-length=100 --exclude=venv,temp,.git,.pytest_cache,__pycache__ lib/ tests/ scripts/ main.py reauth.py

# Запуск приложения
python main.py
```

- **Всегда `python -m pytest`**: голый `pytest.exe` (Scripts\pytest.exe) не кладёт корень репо в `sys.path`, и `lib.*` не импортируется (Windows).
- Файла `.flake8`/`setup.cfg` нет: лимит 100 и эксклюды задаются исключительно флагом CLI (как выше).
- mypy: конфиг `mypy.ini`, запуск **неблокирующий** — `python scripts/check_types.py` (строгие зоны `lib/voice_cmd`, `lib/core`); в pre-commit не входит, пока зоны не чисты (тогда флаг `--fail`).
- Живые тесты (`tests/browser/test_youtube_live.py`, `tests/google/test_calendar_live.py`, `tests/taskflow/test_task_live.py`, live-громкость) требуют окружения — браузер CDP на `:9222`, OAuth-токены — и флейкят. Pre-commit гоняет **весь** набор, так что без рабочего окружения коммит может упасть на живом тесте.

## 4. Архитектура (wiring)
- Цепочка: `main.py` → `lib/stt/transcription_worker.py` (цикл: Vosk → `_fix_encoding` → обработка) → `Orchestrator.process_text` в `lib/core/orchestrator.py`.
- `Orchestrator` — набор миксинов в `lib/core/`: `orchestrator.py` (детерминированное ядро), `orchestrator_decision.py` (уровень Laya), `orchestrator_memory.py` (алиасы запомни/забудь), `orchestrator_opencode.py` (фолбэк), `orchestrator_speech.py` (стоп-слова, dev-режим).
- Уровни обработки текста (по порядку):
  1. `commands.json` — детерминированный матч (правило «трёх строк», §10);
  2. decision-слой Laya — распознанные Laya команды, `lib/core/laya_decision.py`, §4.2;
  3. legacy mini-intent — `lib/voice_cmd/intent.py` (фабрика `build_intent`);
  4. фолбэк — console opencode (`lib/opencode/opencode_cli.py`).
- Конфиг команд устройства — `targets/<hostname>/commands.json` (путь определяет `lib/voice_cmd/config_loader.py::get_device_commands_path`). В `requires` команды перечислены статусы (`proxy`, `browser_youtube`, …) — **статусы-требованиЯ блокируют команду** (частая причина «не работает включи ютуб»). VPN-статус заменён на `proxy` в `lib/runtime/status_checkers.py`.

### 4.1 Раскладка `lib/` по доменам
`tests/` зеркалит те же имена папок (`tests/core/`, `tests/google/`, …).
- `lib/core/` — `orchestrator*`, `laya_decision`, `logger`, `output`.
- `lib/stt/` — `transcription_worker`, `vosk_model`.
- `lib/synth/` — `tts_engines`, `tts_playback`.
- `lib/opencode/` — `opencode_cli`, `opencode_output`.
- `lib/voice_cmd/` — `commands*`, `aliases`, `intent`, `config_loader` (шаг 1, §10).
- `lib/scheduling/` — `cron*`, `time_parser*`, `sleep_event`/`wake_event` тесты здесь.
- `lib/taskflow/` — `tasks_*`, `task_start_sheet`.
- `lib/google/` — `google_calendar_events|mutate`, `google_tasks`.
- `lib/browser/` — `cdp_client`, `youtube_browser`, `youtube_live`.
- `lib/runtime/` — `status*`, `media`.
- `lib/skills/` — `skills`, `skill_actions`.
- `lib/diagnostics/` — `diagnose_cli`, `diagnose_supervisor`.
- `lib/versioning/` — `version`, `version_gate`, `version_checker`.
- `lib/providers/` — LLM-провайдеры.

**НЕ переносить в подпапки**: модули, вызываемые как **`python -m lib.X`** из `targets/*/commands.json` и SKILL.md — `tts`, `reminders`, `tasks`, `plans`, `diagnose`, `browser_control`, `google_calendar`, `sleep_event`, `wake_event`, `task_start`. Их пути — часть конфига и навыков; перенос ломает живые shell-команды. Всё остальное — по подпапкам.

### 4.2 Decision-слой Laya
- Конфиг секции `decision` в `targets/<host>/commands.json`: `enabled`, `url` (http://127.0.0.1:8080), `threshold` (~0.5), `auto_launch` (`laya-lab/bin/laya.exe` + gguf-модель).
- `LayaDecision.detect(text)` → `(choice, confidence)` либо `None` (порог из конфига, критерии — id команд). Фабрика `build_decision(matcher, output)` сама читает конфиг; `build_intent` — аналог в `lib/voice_cmd/intent.py`.
- Воркер создаёт их в `lib/stt/transcription_worker.py`. Путь обработки с дефектной речью проверен тестами `tests/core/test_decision_chain.py` («открой я туб» → openyoutube).

## 5. Google Calendar + Tasks + Таблица
- `lib/google_calendar.py` — «напомни …» это **события Calendar** (не Tasks). OAuth: `credentials.json` + `token.json` (в .gitignore). Scope проверяется по `token.json`; при нехватке — интерактивный consent.
- `lib/reminders.py` — парсинг детерминированный; если время не указано → **+60 минут**.
- `lib/google/google_tasks.py` — «добавь задачу …» это записи Google Tasks (список `@default`) через `lib/tasks.py::TaskHandler`; scope `tasks` + `calendar.events` запрашиваются вместе, чтобы ре-авторизация не ломала напоминания. Флаг: `google.tasks.enabled` в `targets/<host>/commands.json` (шаг 0.6 в `lib/core/orchestrator.py`).
- `lib/task_start.py` («я начал/я приступил {задача}») пишет старт в Google Таблицу `real_life_tasks` через `lib/taskflow/task_start_sheet.py` — те же OAuth-creds.
- Сон/пробуждение: `lib/sleep_event.py`, `lib/wake_event.py` правят событие «СОН» в Calendar.

## 6. Аудио и стоп-слова
- `TranscriptionWorker` продолжает писать микрофон и во время TTS (распознавание стоп-слов живо).
- Аборт: `abort_event` поддерживается в TTS и плеере.
- `_fix_encoding` не должен перекодировать уже валидный UTF-8 из Vosk.
- Частые причины «ассистент не остановился» — стоп-слова и кодировка (см. `_fix_encoding` в `lib/stt/transcription_worker.py`).

## 7. LLM-провайдеры
- Активный провайдер: `race` (OmniRouter + LM Studio, первый непустой ответ). Конфиг в `providers.json`, клиенты в `lib/providers/`.

## 8. Стиль и тестирование
- Тесты только в `tests/` (зеркало структуры `lib/`); внешние зависимости мокать (`pytest-mock`).
- В `except Exception` молчать запрещено: логировать через `swallowed()` из `lib/core/errors.py` (для OAuth-сбоев сам добавит подсказку про `reauth.py`); намеренная глухота — только с меткой `# blind-ok` (pre-commit блокирует новые молчаливые места, старые — baseline).
- Новый файл сразу держать ≤200 строк (лимит хука, §9) — проще вынести миксины/фабрики, чем урезать потом.

## 9. Версии и git-хуки
- `VERSION` — семантическая версия (major.minor.patch); `lib/__init__.py::__version__` держит ту же. Синхронизация — `scripts/bump_version.py patch|minor|major`.
- `.git/hooks/pre-commit` (при коммите выполняются ВСЕ проверки, порядок важен; упал — коммит не создан):
  1. `python -m pytest tests/ -q`;
  2. `python scripts/generate_commands_md.py --check` — актуальность COMMANDS.md;
  3. `flake8 --max-line-length=100 --exclude=...` (та же команда, что в §3);
  4. `python scripts/check_blind_except.py --git` — новые `except Exception` обязаны логировать (print/лог/raise/`swallowed()`/`# blind-ok`), сравнение с HEAD;
  5. `python scripts/check_lengths.py --git` — **лимит 200 строк** у каждого файла (py/ps1/bat);
  6. `python scripts/check_tooltips.py --git` — **каждый новый файл обязан иметь описание в `.structure.json`**;
  7. `python scripts/generate_structure.py --check` — STRUCTURE.md должен быть регенерирован.
- Если хук упал: для (4) — заменить глухой `except` на `swallowed(...)` (или `# blind-ok`); для (5) — урезать/разбить файл; для (6)+(7) — добавить строку в `.structure.json` и выполнить `python scripts/generate_structure.py --write`, затем пере-`git add`.
- `.git/hooks/post-commit` сам делает bump (patch) и коммит «Bump version to …» через `--no-verify` (чтобы не было цикла); bump-коммиты агент вручную не создаёт.

## 10. Концепция голосовых команд (commands.json) — ЕДИНСТВЕННО ВЕРНАЯ

Первый уровень обработки — `commands.json`. Вся распознанная речь — это **поток строк** (каждый законченный фрагмент STT = строка).

Обозначения:
- `[ключ]` — ключевое слово: триггер из `triggers` (`алиса`, `пожалуйста`).
- `_команда_` — слово/словосочетание, указывающее на действие (шаблоны из `match`).
- `{настройка}` — слово/словосочетание, определяющее параметр команды (после команды).

Правила поиска команды:
1. Ключ может стоять **где угодно** в потоке — до или после команды.
2. Команда — слово/словосочетание **сразу перед ключом или сразу после ключа**.
3. Команда определяется по **максимальному совпадению ≥ 90%** с match-шаблоном. **Не угадывать**: пользователь должен правильно произносить команды; ниже порога — мимо (ложный вызов).
4. Слова, идущие **дальше после команды** — настройки для неё.
5. Для поиска команды/настроек смотрим **три строки** потока: строка над ключом, строка с ключом, строка после ключа.
6. **Ждём следующую строку** и ищем команду в ней только когда в строке ключа **одни триггеры** (пустое «ядро»: «алиса»/«пожалуйста» и больше ничего). Если слова есть, но совпадение < 90% — **не ждём**: уходим к decision-слою Laya (§4.2) — STT коверкает фразы («открой я туб» вместо «открой ютуб»), и Laya такие варианты ловит.
7. Если вокруг и рядом с ключом команд нет — **ложный вызов, игнорируем**.

Настройки (текущий набор):
- громче/тише: `{немного}` — уменьшить шаг в 2 раза; `{сильно}` — увеличить шаг в 2 раза (база 6% → 12%).

Трассировка этапов печатается в консоль: `[Command] …` (match по commands.json) → `[Decision] Лайя: команда распознана «…» (c=…)` / `команда не распознана (запрос в OmniRouter заглушён, пропускаем)`.

Это уровень 1. Дальше — decision-слой Laya (§4.2), legacy intent и фолбэк opencode; их поведение зафиксировано тестами `tests/core/test_laya_decision.py`, `tests/core/test_orchestrator_intent.py`, `tests/core/test_orchestrator_fallback.py`.