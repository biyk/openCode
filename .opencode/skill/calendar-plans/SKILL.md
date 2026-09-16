---
name: calendar-plans
description: Report the current or next task from the Google Calendar on the voice-control host. Use when the user asks what is on the schedule/plans right now, or says "что у меня сейчас по планам", "что по расписанию", "что у меня в планах", "что мне сейчас делать".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: calendar
---

## What I do

Find the "currently relevant" calendar task and report it: first an event that is running right now (or started within the last 15 minutes), otherwise the nearest future event. Uses Google Calendar events (not Tasks).

This is the exact behavior of `PlansHandler` in `lib/plans.py`, triggered by phrases like «что у меня сейчас по планам» / «по расписанию».

## How to execute

Read the current task directly (handles auth check):

```python
python -c "
from lib.plans import PlansHandler
h = PlansHandler()
print('auth_ready:', h.auth_ready())
print('task:', h.current_task())
"
```

Or list pending events to double-check:

```powershell
python -m lib.google_calendar list --limit 10
```

## Notes

- Requires Google OAuth (`token.json` with `calendar.events` scope); `credentials.json` must exist.
- If `auth_ready()` is False, the app tells the user to say "авторизация"; do not fabricate calendar data.
- Vosk may mangle the word «расписание» into «списанию»/«расписание» variants — the matcher accepts the `расписан…` / `списан…` stem, so treat any of those spoken forms the same.