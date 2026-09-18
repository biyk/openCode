---
name: playpause
description: Toggle media playback play/pause on the voice-control host (Windows). Use when the user asks to pause, play, resume, or toggle media, or says "пауза", "плей", "играй", "включи", "дальше".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: media
---

## What I do

Toggle the active media session between play and pause by sending the VK_MEDIA_PLAY_PAUSE (0xB3) media key via `user32.dll` (PowerShell one-liner).

This is the exact action behind the voice command `playpause` in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

Run the play/pause one-liner from the active command config:

```powershell
powershell -c "$s='using System;using System.Runtime.InteropServices;public class K{[DllImport(\"user32.dll\",CharSet=CharSet.Auto)]public static extern void keybd_event(byte bVk,byte bScan,uint dwFlags,IntPtr dwExtraInfo);public static void k(byte v){keybd_event(v,0,0,IntPtr.Zero);keybd_event(v,0,2,IntPtr.Zero);}}';Add-Type -TypeDefinition $s -ErrorAction Stop;[K]::k(0xB3)"
```

## Notes

- Requires the `media_session` status to be active (`requires: ["media_session"]`). If the host machine allows it, try to (re)establish a media session first; otherwise the command is blocked by design.
- On Linux hosts the equivalent is `playerctl play-pause`.