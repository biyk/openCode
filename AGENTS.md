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