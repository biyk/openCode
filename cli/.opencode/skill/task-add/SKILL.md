---
name: task-add
description: Add a task to Google Tasks on the voice-control host. Use when the user asks to add/create/write a task without a specific time, or says "добавь задачу ...", "создай задачу ...", "запиши задачу ...", "новая задача ...".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: productivity
---

## What I do

Parse a spoken task request («добавь задачу купить хлеб») into a task title and create it in Google Tasks (default list «@default»). Deterministic parser (no LLM); the text after the trigger phrase becomes the task title.

This is the exact behavior of `TaskHandler` in `lib/tasks.py` + `GoogleTasks.create_task` in `lib/google_tasks.py`.

## How to execute

From Python:

```python
cd C:\Users\b5\Desktop\voice; python -c "
from lib.tasks import TaskHandler
h = TaskHandler()
title = h.create('добавь задачу купить хлеб')
print('title:', title)
print('task_id:', h.add_task(title))
"
```

There is a dedicated CLI subcommand for creating tasks (used by the
`task-add` voice command in `commands.json`):

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.tasks create "создай задачу купить хлеб"
```

It prints `task: <название>` and `task_id: <id>`. Auth is required (`token.json` with `tasks` scope; the consent also requests `calendar.events` so reminders keep working).

## Notes

- Each task becomes an item in the default Google Tasks list («@default»); Tasks does not store a create time.
- Trigger phrases: «добавь задачу», «создай задачу», «добавить задачу», «создать задачу», «запиши задачу», «запиши в задачи», «добавь в задачи», «новая задача».
- An empty phrase after the trigger produces no task — report that the meaning is unclear.
- Do not invent tasks when not authorized — report that auth is needed first.