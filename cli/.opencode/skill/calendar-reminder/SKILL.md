---
name: calendar-reminder
description: Create a reminder in Google Calendar on the voice-control host. Use when the user asks to remember something at a time, or says "напомни ...", "напомни мне через 3 часа ...", "поставь напоминание", "создай напоминание".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: calendar
---

## What I do

Parse a spoken reminder («напомни мне через 3 часа постирать бельё») into a time + text, then create a Google Calendar event with a popup reminder. Deterministic parser (no LLM); if no time is mentioned, the reminder defaults to +60 minutes.

This is the exact behavior of `ReminderHandler` in `lib/reminders.py` + `GoogleCalendar.create_reminder` in `lib/google_calendar.py`.

## How to execute

From Python:

```python
cd C:\Users\b5\Desktop\voice; python -c "
from lib.reminders import ReminderHandler
h = ReminderHandler()
spec = h.create('напомни через 3 часа постирать бельё')
print('spec:', spec)
print('event_id:', h.add_event(spec))
"
```

There is a dedicated CLI subcommand for reminders (used by the
`calendar-reminder` voice command in `commands.json`):

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.reminders "через 3 часа постирать бельё"
```

It prints `reminder: <текст> @ <время>` and `event_id: <id>`. Auth is required (`token.json` with `calendar.events`).

## Notes

- Each reminder becomes a Calendar event (duration 30 min, popup in the start moment by default).
- Trigger phrases: «напомним», «напомни», «поставь напоминание», «создай напоминание», «добавь напоминание», «запомнить», «напомнишь».
- If time parsing fails (e.g. «напомни погулять»), event is created 60 minutes from now.
- Do not invent events when not authorized — report that auth is needed first.