---
name: openyoutube
description: Open the YouTube homepage in the browser via CDP on the voice-control host. Use when the user asks to open, launch, or start YouTube, or says "открой ютуб", "запусти ютуб", "включи ютуб".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: browser
---

## What I do

Open `https://youtube.com` in a new browser tab using the repo's CDP helper (`lib/browser_control.py`), which starts Brave with a remote-debugging port if needed.

This is the exact action behind the voice command `openyoutube` in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control open-url "https://youtube.com"
```

Check readiness first if needed:

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control status
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control tabs
```

## Notes

- Requires the `vpn` status to be active (`requires: ["vpn"]`).
- Sets `provides: ["browser_youtube"]` after success.
- The browser opens a dedicated CDP profile inside the repo (`.voice-cdp-profile-9222`) using Brave.
- Exit code 0 = opened OK; 1 = failed (browser not found or CDP didn't answer).