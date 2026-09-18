# Voice Control Project - Agent Guidelines

## 0. Version gate (NOW)
- `main.py` periodically checks that **app version** (`lib/__init__.py::__version__`) equals **project version** (`VERSION`).
- On mismatch the process must exit (hard exit from the version checker thread via `os._exit(1)`).
- If tests fail or voice behaviour changed: verify `lib/version_gate.py` + `lib/version_checker.py` first.

## 1. Build / Lint / Test Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install flake8 pytest-mock

# Run all unit tests
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_orchestrator.py -v

# Run a single test
python -m pytest tests/test_orchestrator.py::test_process_text_llm_answer -v

# IMPORTANT: bare `pytest.exe` (Scripts\pytest.exe) fails to import lib.* on
# Windows because its sys.path doesn't include repo root. Always use
# `python -m pytest` to ensure the repo root lands on sys.path[0].

# Run linting
flake8 --max-line-length=100 .

# mypy is BROKEN in this repo — skip it.

# Run the application
python main.py
```

## 2. Architecture (wiring)
- `main.py` — entry point. Main loop: Vosk STT → `_fix_encoding` → `_process_text` → `Orchestrator.process_text`.
- `lib/orchestrator.py` — deterministic core; reminders are created via `ReminderHandler`.

## 3. Google Calendar reminders (only)
- `lib/google_calendar.py` — reminders are **Calendar events** (not Tasks). Uses OAuth (`credentials.json` + `token.json`, token in .gitignore).
- `lib/reminders.py` — «напомни мне …» parsing is deterministic; if time missing → **+60 минут**.
- `lib/google_calendar.py` checks token scope by reading `token.json` scopes; if `calendar.events` missing → starts interactive consent.
- `lib/google_tasks.py` — **tasks** («добавь задачу …») are items in Google Tasks (default list `@default`), created via `lib/tasks.py::TaskHandler`. Uses the same `token.json`; scope `tasks` + `calendar.events` requested together so re-auth does not break reminders.
- Feature flag: `google.tasks.enabled` in `targets/<host>/commands.json` (wired in `main.py`), orchestrator step 0.6 in `lib/orchestrator.py`.

## 4. Audio + stop words
- `TranscriptionWorker` keeps recording mic audio while TTS plays (stop-word recognition stays active).
- Stop abort: `abort_event` is supported across TTS + playback.

## 5. Windows gotchas
- `_fix_encoding` must not recode already-valid UTF-8 from Vosk.
- Abort/stop words and encoding issues are common causes of "it didn't stop" reports.

## 6. LLM providers
- Active provider: `race` (OmniRouter + LM Studio, first non-empty wins).

## 7. Style & testing conventions
- Tests in `tests/` only; mock external deps.
- Run tests with `python -m pytest` (Windows import path).

## 8. Version management & git hooks
- `VERSION` file holds semantic version (major.minor.patch).
- `lib/__init__.py` holds `__version__` (updated by bump script).
- `scripts/bump_version.py` increments version (patch/minor/major).
- `.git/hooks/pre-commit` runs `pytest` + `flake8` (aborts on failure).
- `.git/hooks/post-commit` auto-bumps version and creates bump commit (`--no-verify` to avoid loop).

## 9. Концепция голосовых команд (commands.json) — ЕДИНСТВЕННО ВЕРНАЯ

Первый уровень обработки — `commands.json`. Вся распознанная речь —
это **поток строк** (каждый законченный фрагмент STT = строка).

Обозначения:
- `[ключ]` — ключевое слово, на которое опираемся: триггер из `triggers`
  (`алиса`, `пожалуйста`).
- `_команда_` — слово или словосочетание, указывающее на действие
  (шаблоны из `match`).
- `{настройка}` — слово или словосочетание, определяющее параметр
  команды (после команды).

Правила поиска команды:
1. Ключ может стоять **где угодно** в потоке — до или после команды.
2. Команда — слово/словосочетание **сразу перед ключом или сразу после
   ключа**.
3. Команда определяется по **максимальному совпадению ≥ 90%** с
   match-шаблоном. **Не угадывать**: пользователь должен правильно
   произносить команды; ниже порога — мимо (ложный вызов).
4. Слова, идущие **дальше после команды** — это настройки для неё.
5. Для поиска команды/настроек смотрим **три строки** потока:
   - строка над ключом;
   - строка с ключом;
   - строка после ключа.
6. Если команды не было найдено ранее (в строке с ключом её нет) —
   **ждём следующую строку ввода** и ищем команду в ней.
7. Если вокруг и рядом с ключом команд нет — **ложный вызов, игнорируем**.

Примеры:

```
да блин
какая же ты тупая [Алиса]
_сделай громче_ {немного}
```

```
как же меня это достало
_выключи_
[Пожалуйста]
```

```
[Алиса] _сделай громче_
[ключ] громче - {немного}
```

Настройки (текущий набор):
- громче/тише: `{немного}` — уменьшить шаг в 2 раза;
  `{сильно}` — увеличить шаг в 2 раза (если текущий шаг 6% — сделать 12%).

Это касается **только первого шага** (`commands.json`). Остальные уровни
(алиасы/intent/opencode) переделываются позже, после полировки шага 1
тестами.