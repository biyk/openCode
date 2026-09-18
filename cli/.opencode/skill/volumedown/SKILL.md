---
name: media-volume-down
description: Decrease the system volume on the voice-control host (Windows). Use when the user asks to turn the volume down, make it quieter, lower the volume, or says "тише", "сделай тише", "уменьши громкость", "громкость вниз".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: media
---

## What I do

Lower the Windows system volume by sending three VK_VOLUME_DOWN (0xAE) media-key presses via `user32.dll`.

This is the exact action behind the voice command `volumedown` in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

Run the volume-down script for the active host:

```powershell
cd C:\Users\b5\Desktop\voice; powershell -ExecutionPolicy Bypass -File "targets/FLTP-5i3-16512/commands/volumedown.ps1"
```

Verify that the host matches `platform.node()`; if the host differs, locate the script under `targets/<node>/commands/` or fall back to the default `targets/commands.json` definition.

## Notes

- The script is a small Add-Type shim around `keybd_event`; no extra arguments are needed.
- No status checks required — this command has no `requires` entries.