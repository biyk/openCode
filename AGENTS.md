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

- `main.py` — entry point. `TranscriptionWorker` (main.py:91) : `audio_callback` (main.py:110) ALWAYS puts mic audio into the queue (recording never stops, even during TTS — needed for stop words). Main loop runs Vosk STT → `_process_text` (main.py:170) which just delegates to `Orchestrator.process_text`.
- **`lib/orchestrator.py` — `Orchestrator` is the deterministic decision core** (Matcher only import from lib.*): state `_speaking`, `_abort_playback` (threading.Event), `_suppress_until`; methods `process_text`/`_speak_async`/`_on_speaking_finished`/`stop`. `process_text` pipeline: (1) if inside suppress-window after playback → ignore; (2) if `_speaking` (TTS/playback active) → respond ONLY to `STOP_WORDS = {"стоп","останови","stop","хватит","прекрати"}` (main.py:36): sets `_abort_playback` and prints `[TTS] Озвучка прервана`; (3) ordinary path: `CommandMatcher.has_trigger(text)` (triggers from commands.json, NOT `LLM_TRIGGER`) → command `find()`/`execute()` prints echo, otherwise LLM.
- **Stop-word → abort playback**: `_speaking=True; _abort_playback.clear(); _speak_async(answer)` (orchestrator) plays TTS in a background thread; `_on_speaking_finished` resets `_speaking`, sets suppress-window (default 0.5s, `suppress_after`) and calls optional `clear_speech_buffer`. `speak_and_play(..., abort_event)` in `lib/tts.py`.
- `lib/config_loader.py` — device config path resolution: `targets/<hostname>/commands.json` → `targets/commands.json`.
- `lib/providers/manager.py` — `ProviderManager` loads `providers.json`, `get_client(**kwargs)` imports the active provider's module and instantiates it with kwargs.
- **Active provider is `omni` (OmniRouter)** in `providers.json`. This is a local OpenAI-compatible gateway at `http://localhost:20128/v1` — server must be running separately. Default model: **`auto`** (`lib/providers/omni.py:20`, OmniRouter picks). No auth for `/v1/chat/completions`.

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
- OmniRouterClient: timeout default 300s (`lib/providers/omni.py:18`), passed to `requests.post`; configurable via `get_client(..., timeout=N)`.

## 4. Commands

- Commands in `targets/commands.json`: `match` maps spoken templates → command ids; `commands` maps ids → shell strings (or per-OS dict with `windows`/`linux`/`default` keys).
- `CommandMatcher` auto-reloads on file mtime change (`reload()` at commands.py:30) — no app restart needed.
- Media play/pause for this machine is configured in `targets/FLTP-5i3-16512/commands.json`.
- Command config is EXPLICITLY device-specific — edit `targets/<hostname>/commands.json`, not the default, when targeting this machine.

## 5. Windows-Specific Gotchas

- Console shows mojibake for Russian on Windows (cp866) — this is normal console encoding, NOT a code bug.
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