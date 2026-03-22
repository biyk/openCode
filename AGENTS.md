# Voice Control Project - Agent Guidelines

## 1. Build / Lint / Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Install pytest for testing
pip install pytest

# Run all unit tests
pytest tests/ -v

# Run a single test file
pytest tests/test_commands.py -v

# Run a single test
pytest tests/test_commands.py::test_find_command -v

# Run linting (flake8) and type checking (mypy)
flake8 .
mypy .

# Run the application
python main.py

# Download Vosk models (automatic on first run)
# Models are stored in ./models/

# Audio playback requires mpg123 or ffplay
# Install on Ubuntu/Debian: sudo apt install mpg123
# Install on macOS: brew install mpg123
```

## 2. Code Style Guidelines

### Imports
- Standard library imports first, then third‑party, then local modules.
- One import per line, grouped alphabetically within each group.
- Use explicit imports; avoid `from module import *`.
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
- 4 spaces for indentation, no tabs.
- Maximum line length: 100 characters (soft limit).
- Trailing commas allowed in multi‑line structures.
- Blank lines separate logical sections.

### Type Hints
- Use `Optional[T]` for possibly‑null values.
- Annotate function parameters and return values.
- Prefer `list[str]` over `List[str]` (Python 3.9+).

### Naming Conventions
| Element | Convention | Example |
|---------|------------|---------|
| Modules | `snake_case` | `command_matcher.py` |
| Classes | `PascalCase` | `TranscriptionWorker` |
| Functions / Variables | `snake_case` | `ensure_vosk_model()` |
| Constants | `UPPER_SNAKE` | `DEFAULT_SR` |
| Private members | leading underscore | `_running` |

### Error Handling
- Prefer specific exception types; catch `Exception` only for logging.
- Return empty collections (`[]`, `{}`) on failure rather than `None`.
- Use `TranscriptionOutput.print_error()` for CLI error output.
- Wrap I/O operations in `try/except` and raise `RuntimeError` for recoverable failures.

### Documentation
- Module‑level docstrings describing purpose and public API.
- Class and method docstrings in Russian, concise, with parameter descriptions.
- Inline comments only where the code's intent is not obvious.

## 3. Project Structure
```
voice/
├── main.py              # Entry point, STT worker
├── commands.json        # Voice command templates & shell commands
├── requirements.txt     # Python dependencies
├── .env                 # API keys (OPENROUTER_API_KEY, GIGACHAT_API_KEY, etc.)
├── .gitignore           # Excludes: .env, __pycache__, models/, logs/
├── TODO.md              # Task tracking
├── tests/               # Unit tests
│   ├── __init__.py
│   ├── test_commands.py # Tests for CommandMatcher
│   ├── test_openrouter.py # Tests for OpenRouterClient
│   └── test_output.py   # Tests for TranscriptionOutput
├── lib/                 # Core modules
│   ├── commands.py       # Voice command matching & execution
│   ├── gigachat.py      # GigaChat API client (in development)
│   ├── logger.py        # Logging and LLM conversation history
│   ├── openrouter.py    # OpenRouter LLM client
│   ├── output.py        # Console output helper
│   └── tts.py           # Text-to-speech (gTTS)
├── prompts/             # LLM prompt templates
│   └── chat_template.txt # System prompt for chat
└── models/              # Vosk STT models (auto-downloaded)
```

## 4. Environment Variables (.env)
```
OPENROUTER_API_KEY=...      # OpenRouter API key
GIGACHAT_API_KEY=...        # GigaChat API credentials
GIGACHAT_CLIENT_ID=...      # GigaChat client ID
GIGACHAT_API_SCOPE=...      # GigaChat scope (e.g., GIGACHAT_API_PERS)
```
**Important**: Never commit `.env` to version control.

## 5. Adding New Features

### Add a new voice command
1. Edit `commands.json` with shell command and match phrases
2. Restart the application

### Add a new LLM client
1. Create new module in `lib/` (e.g., `lib/gigachat.py`)
2. Follow the pattern of `lib/openrouter.py`
3. Update `main.py` to use the new client

### Modify audio settings
Adjust `DEFAULT_SR` and `BLOCKSIZE` constants in `main.py`.

## 6. TODO Management
- После каждого коммита проверять `TODO.md` — реализует ли текущий функционал какую-либо задачу из списка.
- Если да — отмечать соответствующий пункт галочкой (`[x]`).
- Если после коммита функционал реализован полностью — удалять пункт из TODO.md.

## 7. Cursor / Copilot Rules
- No `.cursor/rules/` or `.github/copilot-instructions.md` files detected.
- If such files are added later, they will be read automatically by the agent.
