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

Open a YouTube tab in the CDP browser (creating it if needed, otherwise switching to an already-open one), then wait until the homepage video list loads, let browser extensions finish running, and finally open the first (non-ad) video from that list.

This is the exact action behind the voice command `openyoutube` in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control youtube-first
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
- Exit code 0 = opened OK; 1 = failed (browser not found or the list didn't load in time).