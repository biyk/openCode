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

If no YouTube tab is open: open youtube.com, wait for the homepage list and extensions, then open the first (non-ad) video. If a YouTube watch tab is already open: switch to it and play the current video. If only the homepage is open: open the first video from the list.

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
- Exit code 0 = opened/played OK; 1 = failed (browser not found, list didn't load, or play failed).