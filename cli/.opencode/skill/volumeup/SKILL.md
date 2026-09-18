---
name: media-volume-up
description: Increase the system volume on the voice-control host (Windows). Use when the user asks to turn the volume up, make it louder, increase volume, or says "громче", "сделай громче", "увеличь громкость", "громкость вверх".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: media
---

## What I do

Raise the Windows system volume by sending three VK_VOLUME_UP (0xAF) media-key presses via `user32.dll`.

This is the exact action behind the voice command `volumeup` in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

Run the volume-up script for the active host:

```powershell
cd C:\Users\b5\Desktop\voice; powershell -ExecutionPolicy Bypass -File "targets/FLTP-5i3-16512/commands/volumeup.ps1"
```

Verify that the host matches `platform.node()`; if the host differs, locate the script under `targets/<node>/commands/` or fall back to the default `targets/commands.json` definition.

## Notes

- The script itself is a small Add-Type shim around `keybd_event`; no extra arguments are needed.
- No status checks required — this command has no `requires` entries.