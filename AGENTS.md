# Voice Control Project - Agent Guidelines

## 1. Build / Lint / Test Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install flake8 pytest-mock

# Run all unit tests
python -m pytest tests/ -v          # 439 tests

# Run a single test file
python -m pytest tests/test_orchestrator.py -v

# Run a single test
python -m pytest tests/test_orchestrator.py::test_process_text_llm_answer -v

# IMPORTANT: bare `pytest.exe` (Scripts\pytest.exe) fails to import lib.* on
# Windows because its sys.path doesn't include repo root.  Always use
# `python -m pytest` to ensure the repo root lands on sys.path[0].

# Run linting (IMPORTANT: no .flake8 config exists, default limit is 79)
flake8 --max-line-length=100 .

# mypy is BROKEN in this repo (duplicate module names error) — skip it.

# Run the application
python main.py

# Audio playback requires mpg123 (installed) or ffplay
# main.py auto-adds bin/mpg to PATH on Windows if it exists
```

## 2. Architecture

- `main.py` — entry point. `TranscriptionWorker` : `audio_callback` ALWAYS puts mic audio into the queue (recording never stops, even during TTS — needed for stop words). Main loop: Vosk STT → `_fix_encoding` (main.py:24) → `_process_text` → `Orchestrator.process_text`. On Windows starts with `chcp 65001` + `sys.stdout/stderr.reconfigure(utf-8)` (main.py:15-22).
- **`lib/orchestrator.py` — deterministic decision core**: state `_speaking`, `_abort_playback` (threading.Event), `_suppress_until`, `_llm_active`, `_llm_queue` (queue.Queue); methods `process_text`/`maybe_abort`/`_speak_async`/`_on_speaking_finished`/`stop`.
  **Pipeline in `process_text`** (each step returns on match):
  1. Suppress window → ignore
  2. `_speaking` → `maybe_abort` only (stop-word kills TTS)
  3. `_llm_active` → `maybe_abort` (stop-word cancels pending LLM answer; non-stop words fall through to normal command processing — voice input is NOT blocked while LLM thinks)
  4. No trigger → `print_text` only, no command processing
  5. Memory commands: «запомни/забудь» (aliases)
  6. Reminders: «напомни мне …» (Google Calendar, `google.enabled` flag) — событие со всплывающим попапом; если время не указано → +60 минут.
  7. Literal match: exact template equality (no substring matching)
  8. Alias match: known garbled phrases from `aliases.json`
  9. Intent classifier: `llm.classify()` or `llm.ask()`
  10. Skills registry: `skills/*.json`
  11. **Async LLM chat**: text → `_llm_queue` → background daemon worker → `llm.ask()` → speak. **process_text returns immediately** — voice input stays active.

  Context for LLM: `{triggers, statuses, requires, blocked}` — enabled triggers, all commands with phrases+requires, live status values, literal-but-blocked candidates; garbled Vosk («ютюб» for «ютуб») is resolved by LLM, which answers id or NONE. LLM-picked id with unmet requires → `[Blocked]` + TTS speaks `need_message`.
- `lib/status.py` — `StatusStore`: system statuses (`vpn`/`media`/`browser_youtube` + custom shell `check`) defined in `targets/<host>/status.json` (sibling of commands.json); background daemon thread polls every `interval` (default 5s), prints `[Status] {name}: on/off` only on change. Built-in checkers: `vpn` = youtube reachable (check-only, never toggles), `media` = `is_media_playing()`, `browser`/`browser_youtube` via CDP. No status file → store disabled → all `requires` pass. Thread-safe; `ensure()` refreshes synchronously when cached value blocks a command.
- `lib/skills.py` — `SkillRegistry`: JSON skills in `targets/<host>/skills/*.json` (name/phrases/params/steps), actions `open_url`/`run_cmd`, `${param}` substitution, reload on change. Gate: `skills.enabled` in commands.json.
- `lib/aliases.py` — `AliasStore` (П6.0): `{core_phrase: {command, hits, confirmed}}` + `pending` in `targets/<host>/aliases.json`, hot-reload on mtime. Orchestrator order: literal → aliases → intent → skills → chat; literal template always beats alias; aliases respect `requires`. Voice teaching: «запомни [X это Y]» (confirm/add), «забудь X»; successful non-literal intent resolutions auto-land in `pending` (`confirmed: false`).
- `lib/google_calendar.py` — напоминания в **Google Calendar** via OAuth 2.0 (Desktop app: `credentials.json` + `token.json`, оба в .gitignore; refresh-token автоматически, `is_ready()` проверяет валидность). `create_reminder(summary, when)` создаёт **событие** в календаре (duration 30 мин, popup напоминание в момент начала по умолчанию). Google Tasks API **не хранит время задачи** (due = полночь всегда), поэтому напоминания живут только в Calendar. CLI: `python -m lib.google_calendar list [--limit N] [--out file]`.
- `lib/reminders.py` — `ReminderHandler`: определяет «напомни мне …» (за флагом `google.enabled`), парсит время через `lib/time_parser.py` (через N час/мин/дней, завтра/сегодня в HH:MM, в HH:MM, в понедельник). Если время не указано — напоминание через **60 минут**. LLM не используется; полностью детерминированный парсинг. `main.py` инстанцирует handler только при `google.enabled`.
- `lib/browser_control.py` — CLI for Chrome DevTools Protocol: `python -m lib.browser_control open-url <url>` (used by `openyoutube` command). Port 9222, `ensure_browser()` launches chrome/brave with `--remote-debugging-port`. Subcommands: `status`, `tabs`, `open-url`, `eval`, `click`, `youtube-play`.
- `lib/intent.py` — `IntentClassifier`: `detect(text, context=None)` — without context uses legacy media_probe prompt, with context uses triggers/statuses/requires/blocked prompt; `_extract_id` pulls the id out even with junk appended (exact → first line → first word → whole-word search, earliest wins).
- `lib/media.py` — `is_media_playing()` via `bin/media_state.ps1`, which checks ALL SMTC sessions for `Playing`; `is_media_available()` runs the same script with `-AnySession`. `playpause`/`stop` require `media_session`, NOT `media`, so paused video can be resumed. `stop` = `targets/<host>/commands/mediastop.ps1`: sends VK_MEDIA_STOP (0xB2), waits 2s, re-checks via `media_state.ps1`, and falls back to Play/Pause (0xB3) if still playing. GOTCHA: `PlaybackStatus` type is `GlobalSystemMediaTransportControlsSessionPlaybackStatus` — compare as string, enum comparison is always False.
- `lib/output.py` — `TranscriptionOutput` (print_text/print_info/print_debug/print_error — always pass output through this, providers announce via it).
- `lib/config_loader.py` — device config path resolution: `targets/<hostname>/commands.json` → `targets/commands.json`.

## 3. LLM Providers

- `lib/providers/__init__.py` defines `BaseLLMClient` (no `base.py`). New providers: implement `ask(text) -> Optional[str]` and `name` property.
- `providers.json` configures all providers; `"active"` field selects which one is used.
- **Active provider: `race`** (`RaceClient` in `lib/providers/race.py`).
  - `RaceClient` sends the request simultaneously to **OmniRouter** (`http://localhost:20128/v1`, model `auto`) and **LM Studio** (`http://localhost:1234/v1`, model `liquid/lfm2.5-1.2b`); first non-empty answer wins, prints `[LLM Race] Отправляю запрос...` / `[LLM Race] Победил: {provider}`. Sub-clients get `announce=False`.
  - LM Studio must be running: `~/.lmstudio/bin/lms.exe server start`. OmniRouter has its own supervisor (§6).
  - `classify(text, timeout=None)` for intent-classification ONLY: skips NONE/empty answers (fast NONE must not kill slow correct id), never writes to LLM history. `IntentClassifier.detect` uses `llm.classify()` when available, else falls back to `ask()`.
- `OmniRouterClient` / `LmStudioClient`: timeout default 300s, passed to `requests.post`. Both accept `announce: bool`.

## 4. Commands

- Commands in `targets/<host>/commands.json`: `match` maps spoken templates → command ids; `commands` maps ids → shell strings (or per-OS dict with `windows`/`linux`/`default` keys); `triggers` lists activation words; `requires` maps id → list of statuses that must be active; `provides` maps id → statuses set True after success; `sequences` maps id → `{steps: [ids]}` run in order, abort on first failure (e.g. `news` = `openyoutube` + `youtube_news`).
- `CommandMatcher(commands_file, status_store=None)` auto-reloads on file mtime change — no app restart needed.
- `find_literal_id(text)` returns id only on EXACT match of `core_phrase` (triggers stripped, lower, ё→е) against a template; `missing_requires(id)` lists unmet statuses; `execute_by_id` enforces `requires` per step (also for sequences and intent-detected ids). `main.py` wires `StatusStore` into the matcher. English templates are removed by design — Vosk is a Russian model, keep all match phrases in Russian.
- Media play/pause is configured in `targets/FLTP-5i3-16512/commands.json`.
- Command config is EXPLICITLY device-specific — edit `targets/<hostname>/commands.json`, not the default.

## 5. Windows-Specific Gotchas

- Console shows mojibake for Russian on Windows (cp866) — this is normal console encoding, NOT a code bug.
- `_fix_encoding` (main.py:24): if text already contains Cyrillic, return as-is (do NOT re-run cp866→utf-8 — it corrupts clean UTF-8 from Vosk); otherwise try the recode for mojibake.
- `VOICE_CONFIRMATION_PHRASE` env var (optional): when set, TTS says it after each executed command.
- TTS fallback chain (per block, `lib/tts.py`): gTTS (online, `timeout=8` in ctor) → local neural `Piper` (`models/piper/ru_RU-irina-medium.onnx`) → Windows `System.Speech` (SAPI5 via `bin/tts_sapi.ps1`). After the first network failure `TextToSpeech._offline` is set and the rest of the batch is synthesized offline. `pyttsx3` is NOT used — unreliable (`runAndWait` deadlock on 2nd `save_to_file`). Piper load is lazy (~3.6 s once, thread-safe).
- `_play_file` picks the player by extension: `.wav` → `PowerShell (New-Object Media.SoundPlayer 'path').PlaySync()`, `.mp3` → mpg123 → ffplay fallback. Temp audio files are unlinked after playback.
- **Abort (stop word)**: `speak`/`speak_and_play`/`_play_file`/`_play_wav`/`_play_mp3` all accept `abort_event`. `_run_player` = subprocess.Popen + 0.05s poll loop; on abort → `terminate()` → False. Synthesis abort: `_speak_and_play_pipeline` uses an explicit `ThreadPoolExecutor` + `shutdown(wait=False, cancel_futures=True)` (NOT a `with` block — it waits for all futures). Piper `synthesize_wav` cannot be interrupted mid-call — it finishes in background without blocking the loop.
- `TextToSpeech.speak_and_play` splits text on `. ! ? … , ; : — – -` (`_SENTENCE_RE` at `lib/tts.py:22`), synthesizes blocks in parallel (`max_workers=4` default) and plays them strictly in order to cut time-to-first-audio.

## 6. Resurrector (Windows process supervisor)

- Config: `C:\Users\b5\.config\resurrector\config.toml`. Runs `python main.py`.
- The `[omniroute]` entry (command='omniroute') MUST stay `enabled=false`: OmniRoute has its own supervisor (its launcher auto-respawns the server), and Resurrector launching a second instance crashes with `EADDRINUSE` on port 20128 → infinite restart loop.
- Resurrector logs to stderr only (needs `-log-file` to persist); no log history by default.

## 7. Style & Testing

- Imports: stdlib → third-party → local; one per line, alphabetical. No `from module import *`.
- 4-space indent, max line length 100. Type hints on all params/returns (`Optional[T]`, `list[str]`, `dict[str, Any]`).
- Docstrings in Russian, Google style. Module-level docstring for each module.
- Tests in `tests/`, named `test_<module>.py`, `test_<method>_<expected_behavior>` naming. Mock external deps (API, I/O, audio). Run tests only inside a `temp/` folder for temp files.
- Never commit `.env` or API keys. After commits, check `TODO.md`.
