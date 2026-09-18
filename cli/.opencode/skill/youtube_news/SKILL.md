---
name: youtube-news
description: Play news videos on YouTube via CDP on the voice-control host. Use when the user asks to play/show news on YouTube, or says "новости ютуб", "новости на ютубе", "включи новости", "покажи новости".
license: MIT
compatibility: opencode
metadata:
  audience: agents
  domain: browser
---

## What I do

Search YouTube for news and play the first result, then ensure the player is running. This covers both the single command `youtube_news` and the `news` sequence (`openyoutube` followed by `youtube_news`).

This is the exact action behind the voice commands `youtube_news` and `news` (sequence) in `targets/FLTP-5i3-16512/commands.json`.

## How to execute

Play the "новости" query directly:

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control youtube-play "новости"
```

For the full `news` sequence, run the two steps in order:

```powershell
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control open-url "https://youtube.com"
cd C:\Users\b5\Desktop\voice; python -m lib.browser_control youtube-play "новости"
```

## Notes

- Requires the `vpn` and `browser_youtube` statuses (`requires: ["vpn", "browser_youtube"]`); the `news` sequence additionally needs `openyoutube` to run first.
- `youtube-play` opens the search URL, waits for the first `ytd-video-renderer` result, clicks it, waits ~5s, then clicks the play button.
- Exit code 0 = video started; 1 = search/click/play failed.