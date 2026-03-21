# Agent Guidelines for Voice Transcription Project

## Project Overview

A lightweight console application for real-time speech-to-text transcription:
- Captures audio via microphone using sounddevice
- Performs speech-to-text using Vosk (offline ASR)
- Prints transcriptions to stdout in real-time

## Build/Run Commands

### Install Dependencies
```bash
pip install -r requirements.txt
```

### Run the Application
```bash
python main.py
```

### Run with Specific Language
Currently set in code (line 142): `lang = "ru"` → change to `"en"` for English

### Vosk Model Downloads
Models are auto-downloaded on first use (~50–60 MB each):
- Russian: `vosk-model-small-ru-0.22` (from alphacephei.com)
- English: `vosk-model-small-en-us-0.15` (from alphacephei.com)
- Stored in `models/` directory

## Code Style Guidelines

### General
- Python 3.10+
- 4-space indentation
- Max line length: ~100 characters (soft limit)
- No automatic formatter configured
- Comment style: `# ---------- Section ----------` for major sections
- Inline comments for single-line clarifications

### Imports
Standard library first, then third-party. One import per line, sorted alphabetically within groups.

```python
import json
import os
import queue
import sys
import threading
import zipfile

from lib.output import TranscriptionOutput

import requests
import sounddevice as sd
from vosk import Model, KaldiRecognizer, SetLogLevel
```

### Type Hints
- Use `Optional[T]` from `typing` for nullable types
- Return type annotations on public methods

```python
from typing import Optional

def ensure_vosk_model(lang_code: str) -> str:
    ...
```

### Naming Conventions
| Element | Convention | Example |
|---------|-----------|---------|
| Classes | CamelCase | `TranscriptionWorker` |
| Functions/variables | snake_case | `ensure_vosk_model`, `model_path` |
| Constants | UPPER_SNAKE_CASE | `DEFAULT_SR`, `BLOCKSIZE` |
| Private members | _leading_underscore | `_running`, `_accumulated` |

### Docstrings
- Use triple-quoted strings for module-level docs and class methods
- Keep descriptions concise
- Include parameter descriptions for complex functions

```python
def ensure_vosk_model(lang_code: str) -> str:
    """
    Ensure Vosk model is present. If missing, download and unzip.
    Returns path to the model directory.
    """
```

### Error Handling
- Wrap file/network operations in try/except blocks
- Raise `RuntimeError` for application-level failures
- Print errors to stderr for CLI apps
- Use specific exception types when possible

```python
try:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
except requests.RequestException as e:
    raise RuntimeError(f"Failed to download: {e}")
```

### Threading
- Use `threading.Event` for stop flags
- Use `queue.Queue` for thread-safe audio buffer communication
- Call `join()` with timeout on thread termination
- Use daemon threads for background workers

## File Structure
```
.
├── main.py              # Main application (console-based STT)
├── lib/                 # Library modules
│   └── output.py        # TranscriptionOutput class
├── requirements.txt     # Dependencies
├── models/              # Vosk model storage (auto-downloaded)
└── README.md            # Project documentation
```

## Key Dependencies
- `sounddevice` - Audio input stream
- `vosk` - Offline speech recognition
- `numpy` - Audio data handling (installed with sounddevice)
- `requests` - HTTP client for model downloads

## Audio Configuration
- Sample rate: 16000 Hz
- Channels: 1 (mono)
- Format: 16-bit PCM (int16)
- Blocksize: 2048 frames

## CLI Output Patterns
Use `TranscriptionOutput` class from `lib.output` for all output:
- `output.print_text(text)` - print transcription
- `output.print_partial(text)` - print with `\r` for live preview
- `output.print_progress(current, total)` - progress indicator
- `output.print_info(message)` - info messages
- `output.print_error(message)` - errors to stderr
- `output.print_stopped()` - stopped message

## Security Notes
- Never commit `.env` files containing secrets
- Use `timeout` on all network requests (60s default)
- Validate downloaded model integrity via file existence checks
