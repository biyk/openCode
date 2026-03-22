# Voice Control Project - Agent Guidelines

## 1. Build / Lint / Test Commands
```
# Install dependencies
pip install -r requirements.txt

# Install pytest for testing
pip install pytest

# Run all unit tests
pytest tests/ -v

# Run a single test file
pytest tests/test_commands.py -v

# Run linting (flake8) and type checking (mypy)
flake8 .
mypy .

# Run the application
python main.py

# Download Vosk models (automatic on first run)
# Models are stored in ./models/
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
- Prefer `list[str]` over `List[str]` (Python 3.9+).

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
- Inline comments only where the code’s intent is not obvious.

## 3. Cursor / Copilot Rules
- No `.cursor/rules/` or `.github/copilot-instructions.md` files detected.
- If such files are added later, they will be read automatically by the agent.

## 4. Project Structure (for reference)
```
voice/
├── main.py              # Entry point, STT worker
├── commands.json        # Voice command templates & shell commands
├── requirements.txt     # Python dependencies
├── .env                 # OPENROUTER_API_KEY (not committed)
├── tests/               # Unit tests
│   ├── __init__.py
│   ├── test_commands.py # Tests for CommandMatcher
│   ├── test_openrouter.py # Tests for OpenRouterClient
│   └── test_output.py   # Tests for TranscriptionOutput
└── models/              # Vosk models (auto‑downloaded)
    └── ...
└── lib/
        ├── output.py    # Console output helper
        ├── commands.py  # Command matching & execution
        └── openrouter.py # LLM client wrapper
```

## 5. Common Development Tasks
- **Add a new voice command** – edit `commands.json` (shell command + match phrases) and restart.
- **Modify audio settings** – adjust `DEFAULT_SR` and `BLOCKSIZE` in `main.py`.
- **Run a single test** – `pytest tests/<test_file>.py -v`.
- **Check for type errors** – `mypy .`.
- **Run lint** – `flake8 .`.
