---
name: speak-answer
description: Voice a short human-readable answer to the user on the voice-control host via TTS. Use at the end of every executed task to report "задача выполнена" or "не удалось выполнить", or whenever the user needs a spoken confirmation of the result.
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: voice
---

## What I do

Synthesize and play a short Russian phrase through the host TTS
(`lib/tts.py::TextToSpeech.speak_and_play`). This is the only way the
console opencode reports task results back to the user.

The phrase must be short (1–2 sentences), in Russian, and state clearly:
- what was done (e.g. «Задача добавлена: накормить хомяка»), or
- that it failed (e.g. «Не удалось выполнить: нет авторизации Google»).

## How to execute

Run from the repository root (this project's `cli/` is a subfolder of the
repo root; python `lib.*` imports only work from the root):

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.tts --b64:0J/QsNGA0L7QsCDQtNC10L3RjC7Qn9C70LDQvdGLINC90LAg0L3QtdC00LXQu9GDLtCQ0LbQv9C1INC/0YDQvtGA0LLQvtGI0Y/QvtGC0Yw=
```

Replace the base64 with `[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('...'))` or simply
pass the phrase as a plain argument when it contains no quotes:

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.tts "Задача выполнена: сделано громче"
```

### Why base64 / `python -m lib.tts`, not `python -c`

- `python -c "from lib.tts import TextToSpeech; TextToSpeech().speak_and_play('фраза')"`
  breaks on Russian text and embedded quotes under the Windows console
  (cp1251 vs utf-8, `unterminated string literal` SyntaxError seen in logs).
- `python -m lib.tts` takes the phrase as an argv item, avoiding inline
  code-with-quotes entirely; `--b64:` is encoding-safe and quote-safe.

Python helper to produce the argument:

```python
import base64
phrase = 'Нет задачи "починить лампочку" в списке'
print('--b64:' + base64.b64encode(phrase.encode('utf-8')).decode('ascii'))
```

## Rules

- Only voice the final answer, once, at the end of the task.
- Do not voice debugging output, tool logs, or intermediate steps.
- If the answer is longer than ~2 sentences, trim it to the essential result.
- If the host cannot voice it (TTS error), print the phrase to stdout instead.