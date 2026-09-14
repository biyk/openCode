# Voice Control Project - Agent Guidelines

## 1. Build / Lint / Test Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install flake8 mypy pytest-mock

# Run all unit tests
pytest tests/ -v

# Run a single test file
pytest tests/test_commands.py -v

# Run a single test
pytest tests/test_commands.py::test_find_command -v

# Run linting
flake8 .

# Run type checking
mypy .

# Run the application
python main.py

# Audio playback requires mpg123 (installed) or ffplay
# main.py auto-adds bin/mpg to PATH on Windows if it exists
```

## 2. Architecture

- `main.py` — entry point. `TranscriptionWorker` (main.py) : `audio_callback` ALWAYS puts mic audio into the queue (recording never stops, even during TTS — needed for stop words). Main loop runs Vosk STT → `_fix_encoding` (main.py:24) → `_process_text` which delegates to `Orchestrator.process_text`. On Windows starts with `chcp 65001` + `sys.stdout/stderr.reconfigure(utf-8)` (main.py:15-22).
- **`lib/orchestrator.py` — `Orchestrator` is the deterministic decision core**: state `_speaking`, `_abort_playback` (threading.Event), `_suppress_until`; methods `process_text`/`maybe_abort`/`_speak_async`/`_on_speaking_finished`/`stop`. `process_text` pipeline: (1) inside suppress-window after playback → ignore; (2) if `_speaking` → respond ONLY to `maybe_abort` (whole-word match against `STOP_WORDS`); (3) ordinary path: require `CommandMatcher.has_trigger(text)` (triggers from commands.json, NOT `LLM_TRIGGER`; FLTP uses `["пожалуйста","алиса"]`), then literal match (`core_phrase` = text minus triggers, exact template equality) → `execute_by_id` (prints `[Command] Распознана команда: {id}`), else `intent.detect(text, context)` → `skills.match` → LLM. No substring matching anywhere: «включи ютуб» never falls into playpause template «включи». Context for LLM: `{triggers, statuses, requires, blocked}` — LLM gets enabled triggers, all commands with phrases+requires, live status values, and literal-but-blocked candidates; garbled Vosk («ютюб» for «ютуб») is resolved by LLM, which answers id or NONE. LLM-picked id with unmet requires → `[Blocked]` + TTS speaks `need_message`.
- `lib/status.py` — `StatusStore`: system statuses (`vpn`/`media`/`browser_youtube` + custom shell `check`) defined in `targets/<host>/status.json` (sibling of commands.json); background daemon thread polls every `interval` (default 5s), prints `[Status] {name}: on/off` only on change. Built-in checkers: `vpn` = youtube reachable (check-only, never toggles — user enables VPN manually), `media` = `is_media_playing()`, `browser`/`browser_youtube` via CDP. No status file → store disabled → all `requires` pass. Thread-safe; `ensure()` refreshes synchronously when cached value blocks a command.
- `lib/skills.py` — `SkillRegistry`: JSON skills in `targets/<host>/skills/*.json` (name/phrases/params/steps), actions `open_url`/`run_cmd`, `${param}` substitution, reload on change. Gate: `skills.enabled` in commands.json.
- `lib/aliases.py` — `AliasStore` (П6.0): `{core_phrase: {command, hits, confirmed}}` + `pending` in `targets/<host>/aliases.json`, hot-reload on mtime. Orchestrator order: literal → aliases (`[Alias]`, `bump()` hits) → intent → skills → chat; literal template always beats alias; aliases respect `requires`. Voice teaching: «запомни [X это Y]» (confirm/add), «забудь X»; successful non-literal intent resolutions auto-land in `pending` (`confirmed: false`).
- `lib/aliases.py` — `AliasStore` (П6.0): `{core_phrase: {command, hits, confirmed}}` + `pending` in `targets/<host>/aliases.json`, hot-reload on mtime. Orchestrator order: literal → aliases (`[Alias]`, `bump()` hits) → intent → skills → chat; literal template always beats alias; aliases respect `requires`. Voice teaching: «запомни [X это Y]» (confirm/add), «забудь X»; successful non-literal intent resolutions auto-land in `pending` (`confirmed: false`).
- `lib/browser_control.py` — CLI for Chrome DevTools Protocol: `python -m lib.browser_control open-url <url>` (used by `openyoutube` command). Port 9222, `ensure_browser()` launches chrome/brave with `--remote-debugging-port`. Subcommands: `status`, `tabs`, `open-url`, `eval`, `click`, `youtube-play`.
- `lib/intent.py` — `IntentClassifier` (mini-LLM fallback for command detection); `detect(text, context=None)` — without context uses legacy media_probe prompt, with context uses triggers/statuses/requires/blocked prompt; `_extract_id` pulls the id out even with junk appended (exact → first line → first word → whole-word search, earliest wins); `lib/media.py` — `is_media_playing()` via `bin/media_state.ps1`, which checks ALL SMTC sessions (not just current) for `Playing`; `is_media_available()` runs the same script with `-AnySession` (True if any session exists, even Paused/Stopped) — `playpause`/`stop` require `media_session`, NOT `media`, so paused video can be resumed; `stop` = `targets/<host>/commands/mediastop.ps1`: sends VK_MEDIA_STOP (0xB2), waits 2s, re-checks via `media_state.ps1`, and falls back to Play/Pause (0xB3) if still playing — YouTube ignores the Stop key; GOTCHA: `PlaybackStatus` type is `GlobalSystemMediaTransportControlsSessionPlaybackStatus`, NOT `Windows.Media.MediaPlaybackStatus` — compare as string, enum comparison is always False; `lib/output.py` — `TranscriptionOutput` (print_text/print_info/print_debug/print_error — always pass output through this, providers announce via it).
- `lib/config_loader.py` — device config path resolution: `targets/<hostname>/commands.json` → `targets/commands.json`.
- **Stop-word → abort playback**: `_speaking=True; _abort_playback.clear(); _speak_async(answer)` (orchestrator) plays TTS in a background thread; `_on_speaking_finished` resets `_speaking`, sets suppress-window (default 0.5s, `suppress_after`) and calls optional `clear_speech_buffer`. `speak_and_play(..., abort_event)` in `lib/tts.py`.
- `lib/providers/manager.py` — `ProviderManager` loads `providers.json`, `get_client(**kwargs)` imports the active provider's module and instantiates it with kwargs.
- **Active provider is `race`** in `providers.json`. `RaceClient` (lib/providers/race.py) sends the request simultaneously to **OmniRouter** (local OpenAI-compatible gateway at `http://localhost:20128/v1`, server must be running separately, model `auto`) and **LM Studio** (`http://localhost:1234/v1`, model `liquid/lfm2.5-1.2b`, launched via `~/.lmstudio/bin/lms.exe server start`); first non-empty answer wins, prints `[LLM Race] Отправляю запрос...` / `[LLM Race] Победил: {provider}`. Sub-clients get `announce=False`; standalone providers print `[LLM] {name} ({model}): запрос` via output when `announce=True`. `classify(text, timeout=None)` is for intent-classification ONLY: skips NONE/empty answers (fast NONE must not kill a slow correct id), never writes to LLM history. `IntentClassifier.detect` uses `llm.classify()` when available (duck-typed), else falls back to `ask()`.

## 2a. Self-learning roadmap (concept in `WORKFLOW.md`)

- Orchestrator = deterministic core (our Python) — mini-LLM/skill-LLM/big-LLM/controller are layers around it; big LLM is NOT the orchestrator.
- Big LLM invoked via **OpenCode CLI** subprocess with omni model/combo; delivers via `targets/<host>/skills/`.
- TDD loop: propose command → user confirms → test → pytest green → write to config.
- Feature-flagged phases: see `TODO.md` "Самообучающийся ассистент — план внедрения". Keep existing stop-word/recording logic intact.
- Existing GitHub research + borrow list: `WORKFLOW.md` §9.

## 3. LLM Provider Contract

- **`BaseLLMClient` is defined in `lib/providers/__init__.py` — there is no `base.py`.** New providers go in `lib/providers/` and implement:
  - `ask(self, text: str) -> Optional[str]`
  - `name` property
- Providers are registered in `providers.json` (`{"id","name","class","module"}`); switch via `"active"` field.
- OmniRouterClient/LmStudioClient: timeout default 300s (constructor params), passed to `requests.post`; configurable via `get_client(..., timeout=N)`. Both accept `announce: bool` — standalone clients print `[LLM]`-line; `RaceClient` sets `announce=False` on sub-clients so only it announces.

## 4. Commands

- Commands in `targets/commands.json`: `match` maps spoken templates → command ids; `commands` maps ids → shell strings (or per-OS dict with `windows`/`linux`/`default` keys); `triggers` lists activation words; `requires` maps id → list of statuses that must be active; `provides` maps id → statuses set True after success; `sequences` maps id → `{steps: [ids]}` run in order, abort on first failure (e.g. `news` = `openyoutube` + `youtube_news`).
- `CommandMatcher(commands_file, status_store=None)` auto-reloads on file mtime change — no app restart needed.
- `find_literal_id(text)` returns id only on EXACT match of `core_phrase` (triggers stripped, lower, ё→е) against a template; `missing_requires(id)` lists unmet statuses; `execute_by_id` enforces `requires` per step (also for sequences and intent-detected ids). `main.py` wires `StatusStore` into the matcher. English templates are removed by design — Vosk is a Russian model, keep all match phrases in Russian.
- Media play/pause for this machine is configured in `targets/FLTP-5i3-16512/commands.json`.
- Command config is EXPLICITLY device-specific — edit `targets/<hostname>/commands.json`, not the default, when targeting this machine.

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