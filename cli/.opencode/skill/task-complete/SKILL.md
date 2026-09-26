---
name: task-complete
description: Complete (mark as done) a Google Tasks item on the voice-control host. Use when the user asks to finish/complete/close a task by name, or says "заверши задачу ...", "выполни задачу ...", "закрой задачу ...", "отметь задачу выполненной ...".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: productivity
---

## What I do

Parse a spoken request («заверши задачу купить хлеб») into a task title,
load the list of *uncompleted* Google Tasks items (default list «@default»),
find a matching task by title, and mark it as completed. Deterministic parser
(no LLM); the text after the trigger phrase becomes the task title.

This is the exact behavior of `TaskHandler.complete_matching` in
`lib/tasks.py` + `GoogleTasks.list_tasks` / `GoogleTasks.complete_task` in
`lib/google/google_tasks.py`.

## How to execute — RUN THE COMMAND, DO NOT LOOK

**You MUST actually run the command below with your shell/bash tool.** The
task is ONLY completed if the command is executed and prints a `result:`
line. Never reply with the command itself or with tool-call markup as your
answer — the answer must be what the command prints.

Run from the repository root (this project's `cli/` is a subfolder of the
repo root; python `lib.*` imports only work from the root):

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.tasks complete "фраза"
```

The phrase is the **user's nominal command**, e.g. «выполнить задачу
подчинить лампочку в ванной пожалуйста». Pass the FULL command as a single
quoted argument, EXACTLY as the user said it — do not paraphrase, do not
"fix" words, do not translate.

**Do NOT try to base64-encode the phrase yourself** — LLMs produce broken
base64. Plain text in the argument is reliable. Only use `--b64:<payload>`
if you are certain about the encoding.

The command prints two lines you must forward as the result:
`title: <название>` and `result: {"matched": [...]}`.

## Matching rules

- Only *uncompleted* tasks are considered; already-completed items are
  ignored (they are not re-marked).
- Exact normalized match (case-insensitive, whitespace-collapsed) wins.
- Else substring match (query is part of the title).
- Else **fuzzy** match via `difflib.SequenceMatcher` ratio >= 0.72 — only
  the single best candidate. This absorbs Vosk speech-recognition noise:
  «починить лампочку ванной» correctly finds «подчинить лампочку в ванной».
- The report item carries `method`: `exact` | `substring` | `fuzzy`.

## Notes

- Auth is required (`token.json` with `tasks` scope; the consent also
  requests `calendar.events` so reminders keep working).
- Complete trigger phrases include: «заверши задачу», «выполни задачу»,
  «выполнить задачу», «выполнив задачу», «закрой задачу», «отметь задачу
  выполненной», «закончи задачу».
- An empty phrase after the trigger produces `result: "matched": []` — report
  that the meaning is unclear.
- `matched: []` means no task with such a title was found — say «задача не
  найдена»; a non-empty list means the task was completed — say «задача
  выполнена: <title>».
- Do not invent tasks when not authorized — report that auth is needed
  first.
- After completing, voice the result with the `speak-answer` skill
  («задача выполнена: <title>» / «задача не найдена»). Pass the phrase to
  `speak-answer` via `python -m lib.tts` (never inline `python -c` with
  embedded quotes).