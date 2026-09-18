    # Project Structure

```
voice/
├── main.py                 # Entry point: STT → orchestrator → TTS
├── providers.json          # LLM providers, active — "race"
├── targets/
│   ├── commands.json       # Default commands
│   └── <hostname>/         # Device-specific overrides:
│       ├── commands.json   #   commands/matches/requires/sequences
│       ├── status.json     #   statuses and checks
│       ├── aliases.json    #   stutter/typo database
│       └── skills/         #   JSON skills (deterministic actions)
├── lib/
│   ├── orchestrator.py     # Deterministic decision core
│   ├── commands.py         # CommandMatcher: trigger/command/settings (≥90%)
│   ├── status.py           # StatusStore: background status polling
│   ├── aliases.py          # AliasStore: typo-to-command mapping
│   ├── skills.py           # SkillRegistry: open_url/run_cmd steps
│   ├── intent.py           # IntentClassifier: LLM classification with context
│   ├── browser_control.py  # CDP browser control (CLI)
│   ├── media.py            # is_media_playing/is_media_available
│   ├── config_loader.py    # commands.json selector by hostname
│   ├── tts.py              # Speech synthesis (gTTS → Piper → SAPI5)
│   ├── logger.py           # Logging and dialog history
│   ├── output.py           # Console output
│   └── providers/          # LLM providers (BaseLLMClient — in __init__.py)
│       ├── __init__.py     # BaseLLMClient: ask() + name
│       ├── manager.py      # ProviderManager
│       ├── race.py         # RaceClient: omni+lmstudio, ask()/classify()
│       ├── omni.py         # OmniRouterClient
│       ├── lmstudio.py     # LmStudioClient
│       ├── openrouter.py
│       ├── gigachat.py
│       ├── deepseek.py
│       └── gpt4free.py
├── bin/
│   ├── media_state.ps1     # Media status via SMTC (all sessions)
│   └── tts_sapi.ps1        # TTS via System.Speech
├── prompts/                # System prompt for LLM
├── models/                 # Vosk models (auto-downloaded)
├── .opencode/              # opencode config
│   └── skill/              # Voice-command duplicates:
│       ├── volumeup/             #   volumeup
│       ├── volumedown/             #   volumedown
│       ├── playpause/              #   playpause
│       ├── stop/                   #   stop
│       ├── openyoutube/            #   openyoutube
│       ├── youtube_news/           #   youtube_news / news
│       ├── calendar-plans/         #   PlansHandler
│       ├── calendar-reminder/      #   ReminderHandler
│       └── browser-automation/     #   generic browser skill
└── tests/                  # pytest tests
```
