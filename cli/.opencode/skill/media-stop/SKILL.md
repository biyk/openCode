---
name: media-stop
description: Stop (or pause as fallback) the active media playback on the voice-control host (Windows). Use when the user asks to stop, halt, or switch off media, or says "стоп", "остановить", "выключи".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: media
---

## What I do

Send VK_MEDIA_STOP (0xB2); if media is still playing after ~2 seconds (e.g. YouTube ignores Stop), fall back to VK_MEDIA_PLAY_PAUSE (0xB3) to pause it.

This is the exact action behind the voice command `stop` in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

Run the media-stop script for the active host:

```powershell
cd C:\Users\b5\Desktop\voice; powershell -ExecutionPolicy Bypass -File "targets/FLTP-5i3-16512/commands/mediastop.ps1"
```

## Notes

- The fallback reads `bin/media_state.ps1` output: `true` means "still playing" → then toggles pause.
- Requires the `media_session` status to be active (`requires: ["media_session"]`).
- On Linux hosts the equivalent is `playerctl stop`.