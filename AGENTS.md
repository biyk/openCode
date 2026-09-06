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

- `main.py` — entry point. `TranscriptionWorker` (main.py:84) captures mic → Vosk STT → `CommandMatcher` (created at main.py:95) → executes matched command; otherwise text with `LLM_TRIGGER` ("пожалуйста", hardcoded at main.py:31) goes to LLM and is spoken via TTS. `LLM_TRIGGER` is NOT read from commands.json — only `history_limit` is (main.py:99).
- `lib/config_loader.py` — device config path resolution: `targets/<hostname>/commands.json` → `targets/commands.json`.
- `lib/providers/manager.py` — `ProviderManager` loads `providers.json`, `get_client(**kwargs)` imports the active provider's module and instantiates it with kwargs.
- **Active provider is `omni` (OmniRouter)** in `providers.json`. This is a local OpenAI-compatible gateway at `http://localhost:20128/v1` — server must be running separately. Model: `ds-web/deepseek-v4-flash-search` (default in `lib/providers/omni.py`). It requires no auth for `/v1/chat/completions`.

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
- `_play_file` picks the player by extension: `.wav` → `PowerShell (New-Object Media.SoundPlayer 'path').PlaySync()` (mpg123 cannot decode WAV), `.mp3` → mpg123 → ffplay fallback. Temp audio files are unlinked after playback.
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