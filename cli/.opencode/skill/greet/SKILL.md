---
name: greet
description: Handle common greetings (привет, здравствуй, добрый день, etc.). Respond with a friendly Russian greeting and ask how you can help. Use this when the user just says hello or a greeting — it is NOT a command to execute.
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: voice
---

## What I do

Respond to a simple greeting with a friendly Russian greeting.
Do NOT treat the greeting as a command to execute.

## When to use

Use this skill when the user says a greeting and nothing more, e.g.:
- "привет"
- "здравствуй"
- "добрый день"
- "доброе утро"
- "добрый вечер"
- "здорово"
- "приветик"
- "здрасте"
- "halla"
- "hello"

Do NOT use this if the user asks for something specific — use the appropriate skill instead.

## How to execute

Just say hello back and ask how you can help:

```
Привет! Чем могу помочь?
```

Then voice it using speak-answer:

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.tts "Привет! Чем могу помочь?"
```

## Rules

- Only respond with a greeting, not a command.
- Keep it short: 1 sentence + a question.
- Do not try to "execute" a greeting — just acknowledge it.
- If the user adds any request to the greeting (e.g. "привет, включи музыку"), handle the request with the appropriate skill instead.
