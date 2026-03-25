# Voice Control Project - Agent Guidelines

## 1. Build / Lint / Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all unit tests
pytest tests/ -v

# Run a single test file
pytest tests/test_commands.py -v

# Run a single test
pytest tests/test_commands.py::test_find_command -v

# Run linting and type checking
flake8 .
mypy .

# Run the application
python main.py

# Audio playback requires mpg123 or ffplay
# Ubuntu/Debian: sudo apt install mpg123
# macOS: brew install mpg123
```

## 2. Code Style Guidelines

### Imports
Standard library → third‑party → local modules. One import per line, alphabetical within groups. No `from module import *`.
```python
import os
import sys
import json
import queue
import threading
from typing import Optional

import sounddevice as sd
import requests
from vosk import Model

from lib.output import TranscriptionOutput
from lib.commands import CommandMatcher
from lib.openrouter import OpenRouterClient
```

### Formatting
- 4 spaces indentation, no tabs
- Max line length: 100 characters (soft limit)
- Trailing commas allowed in multi-line structures
- Use f-strings for string formatting

### Type Hints
- Use `Optional[T]` for possibly-null values
- Annotate all function parameters and return values
- Prefer `list[str]` over `List[str]` (Python 3.9+)
- Use `dict[str, Any]` for JSON-like dictionaries

### Naming Conventions
| Element | Convention | Example |
|---------|------------|---------|
| Modules | `snake_case` | `command_matcher.py` |
| Classes | `PascalCase` | `TranscriptionWorker` |
| Functions / Variables | `snake_case` | `ensure_vosk_model()` |
| Constants | `UPPER_SNAKE` | `DEFAULT_SR` |
| Private members | leading underscore | `_running` |

### Error Handling
- Prefer specific exception types; catch `Exception` only for logging
- Return empty collections (`[]`, `{}`) on failure rather than `None`
- Use `TranscriptionOutput.print_error()` for CLI output
- Wrap I/O in `try/except`, raise `RuntimeError` for recoverable failures
- Never suppress exceptions silently

### Documentation
- Module-level docstrings describing purpose and public API
- Class/method docstrings in Russian, concise, with parameter descriptions
- Google-style docstrings:
```python
def process_audio(data: bytes) -> Optional[dict]:
    """Обрабатывает аудиоданные и возвращает результат распознавания.
    
    Args:
        data: Raw audio bytes from the microphone.
        
    Returns:
        Dict with recognized text or None if recognition failed.
    """
```

## 3. Project Structure
```
voice/
├── main.py              # Entry point, STT worker
├── targets/             # Device-specific command configs
│   └── commands.json    # Default voice commands
├── targets/<hostname>/  # Device-specific overrides
├── requirements.txt     # Python dependencies
├── .env                 # API keys (never commit!)
├── TODO.md              # Task tracking
├── tests/               # Unit tests
│   ├── test_commands.py
│   ├── test_openrouter.py
│   ├── test_output.py
│   ├── test_tts.py
│   ├── test_config_loader.py
│   └── test_logger.py
├── lib/                 # Core modules
│   ├── commands.py      # Voice command matching
│   ├── config_loader.py # Device-specific config loading
│   ├── gigachat.py      # GigaChat API client
│   ├── logger.py        # Logging and LLM conversation history
│   ├── openrouter.py    # OpenRouter LLM client
│   ├── output.py        # Console output helper
│   └── tts.py           # Text-to-speech (gTTS)
├── prompts/             # LLM prompt templates
└── models/              # Vosk STT models (auto-downloaded)
```

## 4. Key Patterns

### Configuration Loading
- Use `lib/config_loader.py` for device-specific config paths
- Config priority: `targets/<hostname>/commands.json` → `targets/commands.json`

### Threading
- Use `threading.Event()` for graceful shutdown signaling
- Use `queue.Queue()` for thread-safe data passing
- Always use `daemon=True` for background threads

### LLM Integration
- All LLM clients follow pattern in `lib/openrouter.py`
- Implement `chat(messages: list) -> str` method
- Use `lib/logger.py` for conversation history

## 5. Testing Guidelines

- Place tests in `tests/` matching module structure
- Use `pytest` as the test framework
- Name test files as `test_<module>.py`
- Use descriptive test function names: `test_<method>_<expected_behavior>`
- Mock external dependencies (API calls, file I/O, audio devices)
- Use `unittest.mock` for patching

```python
def test_find_command():
    matcher = CommandMatcher("tests/fixtures/commands.json")
    result = matcher.find("открой браузер")
    assert result == "firefox"
```

## 6. TODO Management
- После каждого коммита проверять `TODO.md`
- Отмечать реализованные задачи галочкой (`[x]`)
- Удалять полностью реализованные пункты
