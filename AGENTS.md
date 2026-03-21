# Voice Control Project - Agent Guidelines

## Project Overview

Voice-controlled command system using Vosk STT (Speech-to-Text). Recognizes voice commands
and executes corresponding shell commands defined in `commands.json`.

## Project Structure

```
voice/
├── main.py              # Main entry point, STT worker
├── lib/
│   ├── output.py        # Console output handling
│   └── commands.py      # Command matching and execution
├── commands.json        # Command templates and shell commands
├── requirements.txt     # Python dependencies
└── models/              # Vosk models (auto-downloaded)
```

## Dependencies

- `vosk` - Speech recognition
- `sounddevice` - Audio input
- `PyQt6` - GUI (future)
- `requests` - HTTP downloads
- `numpy` - Audio processing

## Build/Test Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py

# Download Vosk models (automatic on first run)
# Models are downloaded to: ./models/
```

## Code Style Guidelines

### General

- 4 spaces for indentation
- Maximum line length: 100 characters
- Use type hints for function parameters and return values
- Private methods/attributes prefixed with `_`
- Docstrings for classes and public methods

### Imports

Standard library imports first, then third-party, then local:
```python
import os
import sys
import json
import queue
import threading
import zipfile
from typing import Optional

import sounddevice as sd
import requests
from vosk import Model

from lib.output import TranscriptionOutput
```

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Modules | snake_case | `command_matcher.py` |
| Classes | PascalCase | `TranscriptionWorker` |
| Functions | snake_case | `ensure_vosk_model()` |
| Variables | snake_case | `default_sr`, `model_path` |
| Constants | UPPER_SNAKE | `DEFAULT_SR`, `BLOCKSIZE` |
| Private | prefixed `_` | `_running`, `_accumulated` |

### Type Annotations

```python
def func(param: str) -> bool:
def func(param: Optional[str] = None) -> Optional[str]:
def func(items: list[str]) -> dict[str, int]:
```

### Error Handling

- Catch specific exceptions when possible
- Return empty collections on failure (not `None`) where appropriate
- Use `except Exception as e:` only for re-raising or logging
- Print errors to stderr using `TranscriptionOutput.print_error()`

```python
# Good
try:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
except Exception:
    return {}

# Better for critical operations
try:
    subprocess.run(cmd, shell=True, check=True)
except subprocess.CalledProcessError:
    return False
```

### Class Structure

```python
class MyClass:
    """
    Brief description of the class.
    """

    def __init__(self, param: str):
        self._param = param
        self._internal_state = None

    def public_method(self, arg: int) -> bool:
        """Describe what this method does."""
        ...

    def _private_method(self) -> None:
        """Internal implementation detail."""
        ...
```

### Module Structure

Each module should have:
1. Imports
2. Constants (module-level)
3. Classes
4. Functions

### Working with Voice Commands

Commands are defined in `commands.json`:
```json
{
    "commands": {
        "volumeup": "pactl set-sink-volume @DEFAULT_SINK@ +10%"
    },
    "match": {
        "volumeup": ["громче", "сделай громче", "увеличь громкость"]
    }
}
```

The `CommandMatcher` class:
- `find(text)` - returns command string if match found, else `None`
- `execute(text)` - finds and executes command via shell

### Audio Configuration

- Sample rate: 16000 Hz (`DEFAULT_SR`)
- Block size: 2048 frames (`BLOCKSIZE`)
- Channels: 1 (mono)
- Format: int16

### Threading

- Use `threading.Event()` for stop flags
- Daemon threads for non-critical background work
- Thread-safe queue (`queue.Queue`) for audio data

## Git Workflow

- Commit messages: concise, imperative mood ("Add feature" not "Added feature")
- Group related changes in single commits
- Run before committing: `git diff` to review changes

## Common Tasks

### Adding a new voice command

1. Edit `commands.json`:
   - Add shell command to `commands` section
   - Add voice templates to `match` section

2. Test by speaking the command

### Modifying audio settings

Adjust constants in `main.py`:
```python
DEFAULT_SR = 16000  # Sample rate
BLOCKSIZE = 2048    # Frames per callback
```

### Adding a new module

1. Create file in `lib/`
2. Add docstring and type hints
3. Import in `main.py` when needed
