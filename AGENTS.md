# Voice Control Project - Agent Guidelines

Голосовой ассистент на Windows: Vosk STT → обработка команд → TTS. Речь — это поток строк STT;
разбор команды идёт по правилу «трёх строк» (см. §10), затем — decision-слой Laya, intent, opencode.

## 1. Git commits — ТОЛЬКО ПО ЯВНОЙ КОМАНДЕ
- **Коммитить, пушить, делать PR запрещено без явной команды пользователя.** Сначала показать результат и ждать подтверждения.
- Исключение: авто-коммиты от хуков (`.git/hooks/post-commit` bump-версии) — их создаёт сам хук, агент не инициирует.
- Без команды не вызывать `git commit` / `git push` / `git add`, даже если задача выглядит завершённой.
- **Окончание разработки озвучивается вслух** («Разработка завершена»): текст — `lib/core/tuning.py::TASK_DONE_TEXT`, произносит его `.git/hooks/post-commit` через `python scripts/announce_done.py` (коммит и есть момент завершения; озвучка на bump-коммите не дублируется — хук выходит до неё). Поэтому «закончил разработку» без слова пользователя — это всё равно не коммит: сначала показать результат и ждать команду, а голос подтвердит факт коммита. Проверено тестами `tests/core/test_tuning.py::TestDevelopmentDoneIsAnnounced` (ловят тихую потерю озвучки).

## 2. Version gate
- `main.py` при старте и в потоке `lib/versioning/version_checker.py` (интервал 120 c) сверяет **app version** (`lib/__init__.py::__version__`) с **project version** (`VERSION`). При несовпадении — жёсткий выход (`os._exit(1)`).
- Если процесс «внезапно выходит» или тесты ломаются — первым делом проверять `lib/versioning/version_gate.py` + `version_checker.py`.
- После bump-коммита `VERSION` и `__version__` синхронны; не рассинхронизировать их вручную.

## 3. Build / Lint / Test Commands (Windows)

```bash
# Все тесты
python -m pytest tests/ -v

# Один файл / один тест
python -m pytest tests/core/test_orchestrator.py -v
python -m pytest tests/core/test_orchestrator.py::TestOrchestratorProcess::test_process_text_command_found -v

# Линейные новые тесты тоже в подпапках-зеркалах: tests/voice_cmd/, tests/runtime/, ...

# Линт — ТОЛЬКО этой командой (совпадает с pre-commit):
flake8 --max-line-length=100 --exclude=venv,temp,.git,.pytest_cache,__pycache__ lib/ tests/ scripts/ main.py reauth.py

# Запуск приложения
python main.py
```

- **Всегда `python -m pytest`**: голый `pytest.exe` (Scripts\pytest.exe) не кладёт корень репо в `sys.path`, и `lib.*` не импортируется (Windows).
- Файла `.flake8`/`setup.cfg` нет: лимит 100 и эксклюды задаются исключительно флагом CLI (как выше).
- mypy: конфиг `mypy.ini`, запуск **неблокирующий** — `python scripts/check_types.py` (строгие зоны `lib/voice_cmd`, `lib/core`); в pre-commit не входит, пока зоны не чисты (тогда флаг `--fail`).
- Живые тесты (`tests/browser/test_youtube_live.py`, `tests/google/test_calendar_live.py`, `tests/taskflow/test_task_live.py`, live-громкость) требуют окружения — браузер CDP на `:9222`, OAuth-токены — и флейкят. Pre-commit гоняет **весь** набор, так что без рабочего окружения коммит может упасть на живом тесте.

## 4. Архитектура (wiring)
- Цепочка: `main.py` → `lib/stt/transcription_worker.py` (цикл: Vosk → `_fix_encoding` → обработка) → `Orchestrator.process_text` в `lib/core/orchestrator.py`.
- `Orchestrator` — набор миксинов в `lib/core/`: `orchestrator.py` (детерминированное ядро), `orchestrator_decision.py` (уровень Laya), `orchestrator_memory.py` (laya/undefined-кандидаты базы знаний), `orchestrator_opencode.py` (фолбэк), `orchestrator_speech.py` (стоп-слова, dev-режим).
- Уровни обработки текста (по порядку):
  1. `commands.json` — детерминированный матч (правило «трёх строк», §10);
  2. decision-слой Laya — распознанные Laya команды, `lib/core/laya_decision.py`, §4.2;
  3. legacy mini-intent — `lib/voice_cmd/intent.py` (фабрика `build_intent`);
  4. фолбэк — console opencode (`lib/opencode/opencode_cli.py`).
- Конфиг команд устройства — `targets/<hostname>/commands.json` (путь определяет `lib/voice_cmd/config_loader.py::get_device_commands_path`). В `requires` команды перечислены статусы (`proxy`, `browser_youtube`, …) — **статусы-требованиЯ блокируют команду** (частая причина «не работает включи ютуб»). VPN-статус заменён на `proxy` в `lib/runtime/status_checkers.py`.

### 4.1 Раскладка `lib/` по доменам
`tests/` зеркалит те же имена папок (`tests/core/`, `tests/google/`, …).
- `lib/core/` — `orchestrator*`, `laya_decision`, `logger`, `output`.
- `lib/stt/` — `transcription_worker`, `vosk_model`, `encoding` (починка cp866).
- `lib/synth/` — `tts_engines`, `tts_playback`.
- `lib/opencode/` — `opencode_cli`, `opencode_output`.
- `lib/voice_cmd/` — `commands*`, `knowledge`, `intent`, `config_loader` (шаг 1, §10).
- `lib/scheduling/` — `cron*`, `time_parser*`, `sleep_event`/`wake_event` тесты здесь.
- `lib/taskflow/` — `tasks_*`, `task_start_sheet`, `fun_holes`/`fun_fill` (дыры календаря).
- `lib/google/` — `google_calendar_events|mutate`, `google_tasks`.
- `lib/browser/` — `cdp_client` (HTTP/WS-примитивы, `wait_until`), `cdp_events` (ожидания по событиям, §4.5), `youtube_browser`, `youtube_live`.
- `lib/runtime/` — `status*`, `media`, `record_gate` + `audio_devices`/`win_com` (Core Audio, §4.6).
- `lib/skills/` — `skills`, `skill_actions`.
- `lib/diagnostics/` — `diagnose_cli`, `diagnose_supervisor`.
- `lib/versioning/` — `version`, `version_gate`, `version_checker`.
- `lib/providers/` — LLM-провайдеры.

**НЕ переносить в подпапки**: модули, вызываемые как **`python -m lib.X`** из `targets/*/commands.json` и SKILL.md — `tts`, `reminders`, `tasks`, `plans`, `diagnose`, `browser_control`, `google_calendar`, `sleep_event`, `wake_event`, `task_start`. Их пути — часть конфига и навыков; перенос ломает живые shell-команды. Всё остальное — по подпапкам.

### 4.2 Decision-слой Laya
- Конфиг секции `decision` в `targets/<host>/commands.json`: `enabled`, `url` (http://127.0.0.1:8080), `threshold` (~0.5), `auto_launch` (`laya-lab/bin/laya.exe` + gguf-модель).
- `LayaDecision.detect(text)` → `(choice, confidence)` либо `None` (порог из конфига, критерии — id команд). Фабрика `build_decision(matcher, output)` сама читает конфиг; `build_intent` — аналог в `lib/voice_cmd/intent.py`.
- Воркер создаёт их в `lib/stt/transcription_worker.py`. Путь обработки с дефектной речью проверен тестами `tests/core/test_decision_chain.py` («открой я туб» → openyoutube).

### 4.3 Фоновый контроль таблицы задач (`task_monitor`)
- `main.py` рядом с CronScheduler поднимает `lib/core/task_monitor.py` (daemon-поток, как version_checker): раз в `interval_min` читает `real_life_tasks` через `lib/taskflow/task_check.py`.
- Ни одной запущенной задачи (`start_date = 0` у всех строк) → вслух «чем ты сейчас занимаешься?», следующая строка STT — ответ: название ищется среди задач таблицы (`TaskStartHandler.find_task_event`) и найденное запускается (`start_task`, то же, что `taskstart`).
- Вопроса «всё ли нормально?» при просрочке нет (убран по решению пользователя): реакция одна — пустая таблица (п.1 выше).
- Вопрос/ответ — `lib/core/orchestrator_ask.py`: строка после вопроса перехватывается ДО уровней §10 и живёт `answer_timeout_s` секунд; просроченный вопрос снимается и переспрашивается в следующий цикл (иначе один неотвеченный заблокировал бы все), «стоп» снимает вопрос. Секция `task_monitor` в `targets/<host>/commands.json` (enabled/interval_min/answer_timeout_s, дефолты — `lib/core/tuning.py`). Тесты: `tests/core/test_task_monitor.py`, `tests/core/test_orchestrator_ask.py`, `tests/taskflow/test_task_check.py`.

### 4.4 Развлечения в дырах календаря (`fun_holes`)
- Тот же поток `task_monitor`, отдельный шаг каждый цикл (независимо от idle/busy и от того, читалась ли таблица): `lib/taskflow/fun_fill.py`.
- **Дыра** — промежуток между двумя соседними событиями `colorId=7` (цвет «сделано» задач приложения), даже если между ними стоят события других цветов. Окно: от конца сегодняшнего «СОН» (пробуждение) до начала последней синей задачи — то есть только прошедшее время, куда автоплан уже не пишет. Промежуток короче `min_gap_min` не заполняется; пересекающиеся галочки сворачиваются бегущим максимумом конца (дыра не может быть отрицательной).
- В дыру вставляется событие `FUN_EVENT_TITLE` («Отдых») на весь промежуток, `colorId` — у сегодняшнего мероприятия «тест для цвета» (пользователь задаёт цвет им; ищется за `lookback_days`, иначе `FUN_FALLBACK_COLOR`). Имя награды `FUN_REWARD_TITLE` («1час развлечений» из `real_life_rewards`) остаётся только в журнале списаний — в календаре оно было бы шумом.
- **Деньги**: `hero_money -= минуты события` (1 минута = 1 hero_money, минус разрешён), и в `rewards_history` идёт строка теми же колонками, что JS-клиент: `uuid | claim_ms | gold_spent | reward_title | reward_id | серий_даты` (`lib/taskflow/rewards_sheet.py`).
- Идемпотентность: развлечение НЕ синее, поэтому соседи по цвету после вставки те же — без маркера одна и та же дыра тратилась бы каждый цикл. Маркер `fun_hole` в `description` события; дыра, внутри которой есть такое событие, пропускается. Озвучки нет (решение пользователя) — виден факт в календаре и в таблице, а **каждое действие пишется в `logs/fun_holes.log`** (JSONL: `action=fill` — дыра, `gold_spent`, `event_id`, `claim_item_id`; `action=run` — итог прохода). Ручная проверка: `python -m lib.taskflow.fun_fill [--dry]`. Тесты: `tests/taskflow/test_fun_holes.py`, `test_fun_fill.py`, `test_rewards_sheet.py`.

### 4.5 Браузер: ждать события страницы, а не время
- Причина: «открой юту» матчится, браузер поднимается, а в ответ — `[Browser] Не удалось запустить текущее видео`. Виноваты паузы: код жал play() по ещё не загрузившейся вкладке и считал это успехом.
- Порядок шагов один для всех сценариев: **порт браузера → событие загрузки → элемент в DOM → факт воспроизведения**. `browser_control.ensure_browser` ждёт ответ `/json/version` (опрос `CDP_POLL_S`, потолок `BROWSER_START_S` — события тут нет), дальше `lib/browser/cdp_events.py`.
- `cdp_events.wait_page_loaded` / `navigate` — подписка `Page.enable` и `Page.loadEventFired` (у навигации ещё ответ `Page.navigate`; `errorText`/`error` = переход не удался). Документ мог загрузиться до подписки — признаком служит `readyState`.
- `cdp_events.wait_condition` / `wait_element` — JS-Promise внутри страницы: `MutationObserver` + редкий `setInterval` (состояние плеера `video.paused` в DOM не отражено). Возврат `false` по истечении `timeout` — это «не дождались», а не ошибка.
- Две ловушки, пойманные только живым браузером: (а) выражение должно быть ОДНИМ `new Promise(...) {...}` без завершающих `()` — иначе `TypeError: (intermediate value) is not a function`; (б) ответ вида `{"error":{ "code":-32000, "Cannot find default execution context"}}` — это не провал условия, а перезапуск документа: запрос повторяем до дедлайна.
- Таймауты в `lib/core/tuning.py` — только страховки от зависшей вкладки (`CDP_PAGE_LOAD_S`, `CDP_ELEMENT_S`, `BROWSER_START_S`); `CDP_FIRST_TRY_S` — короткая первая проба: сразу после клика/перехода страница ещё документ-заглушка, поэтому `_wait_player_ready` пробует сначала быстро, потом по-настоящему.
- Проигрывание проверяется по состоянию страницы (`!document.querySelector('video').paused`), а не по тому, что вернул внедрённый скрипт. `wait_for_selector` из `cdp_client` удалён — его заменил `cdp_events.wait_element`.
- Тесты: `tests/browser/test_cdp_events.py` (FakeWs, обе ловушки из п. выше), `test_youtube_open_first.py` (порядок шагов «открой юту»), `test_youtube_browser.py`, `test_youtube_live_unit.py`; живой — `tests/browser/test_youtube_live.py` (нужен браузер на `:9222`).

### 4.6 Шлюз захвата микрофона (`record_gate`)
- Правило: **звук идёт НЕ через разрешённое устройство (наушники) и на нём играет медиа → микрофон не пишется**. С колонок медиа попадает в микрофон, и ассистент распознаёт чужую речь вместо команд; в наушниках утечки нет, там запись всегда открыта.
- `lib/runtime/record_gate.py::RecordGate` — daemon-поток (тот же порядок, что `task_monitor`), раз в `poll_s` читает Core Audio: `default_device_name()` + `active_session_processes(min_peak)` (`lib/runtime/audio_devices.py`, ctypes-COM через `lib/runtime/win_com.py`). Колбэк sounddevice только читает готовый `blocked` — COM в аудио-поток реального времени не пускаем.
- «Играет» решает **пик-метр сессии** (`IAudioMeterInformation::GetPeakValue`), а не `AudioState` — ловушка, найденная живой замером: спящий VLC висит `Active` с пиком 0.0 (по одному состоянию шлюз глушил микрофон непрерывно), а SoundPlayer играет при `state=1` с пиком 0.6. Порог — `RECORD_GATE_MIN_PEAK` (`record_gate.min_peak`); из состояний отсекаем только `Muted` (в микрофон такой не утекает). Метр не ответил — не считаем медиа (fail-open).
- Глушим **полностью** (решение пользователя): вместе с командами не слышны и стоп-слова. Выход из заглушения — пауза медиа или возврат на наушники; на каждом переключении worker сбрасывает распознаватель (`take_change()`), иначе склеился бы обрывок команды с музыкой.
- Своя озвучка в медиа **не** считается: TTS играет из дочерних `powershell`/`mpg123`/`ffplay` (`lib/synth/tts_playback.py`), и учти мы их — шлюз закрывался бы сразу после каждой фразы ассистента. Список — `ignored_processes`.
- Любой сбой проверки (COM, не Windows, неизвестное устройство) — **открытый** шлюз (fail-open): оглохнуть из-за сломанного условия хуже, чем из-за музыки.
- Секция `record_gate` в `targets/<host>/commands.json` (enabled/allowed_device/poll_s/min_peak/ignored_processes), дефолты — `lib/core/tuning.py` (`RECORD_GATE_*`; allowed_device — подстрока имени, регистр не важен). Шлюз собирает `build_record_gate(matcher, output)` в `__init__` worker'а, запускает `run()`, снимает `stop()`.
- Тесты: `tests/runtime/test_audio_devices.py` (что считается звуком: тишина при Active, пик при state=1, мьют, мёртвый метр), `tests/runtime/test_record_gate.py` (таблица случаев правила, fail-open, скидка на свой TTS, фабрика), `tests/stt/test_worker_record_gate.py` (колбэк и цикл захвата); живые проверки — `python temp/gate_peak.py` (пики всех сессий + вердикт из реального конфига) и `python temp/gate_peak2.py` (поднимает `temp/play_loop.ps1` и показывает, что шлюз закрывается ровно в моменты звука).

## 5. Google Calendar + Tasks + Таблица
- `lib/google_calendar.py` — «напомни …» это **события Calendar** (не Tasks). OAuth: `credentials.json` + `token.json` (в .gitignore). Scope проверяется по `token.json`; при нехватке — интерактивный consent.
- `lib/reminders.py` — парсинг детерминированный; если время не указано → **+60 минут**.
- `lib/google/google_tasks.py` — «добавь задачу …» это записи Google Tasks (список `@default`) через `lib/tasks.py::TaskHandler`; scope `tasks` + `calendar.events` запрашиваются вместе, чтобы ре-авторизация не ломала напоминания. Флаг: `google.tasks.enabled` в `targets/<host>/commands.json` (шаг 0.6 в `lib/core/orchestrator.py`).
- `lib/task_start.py` («я начал/я приступил {задача}») пишет старт в Google Таблицу `real_life_tasks` через `lib/taskflow/task_start_sheet.py` — те же OAuth-creds.
- Сон/пробуждение: `lib/sleep_event.py`, `lib/wake_event.py` правят событие «СОН» в Calendar.

## 6. Аудио и стоп-слова
- `TranscriptionWorker` продолжает писать микрофон и во время TTS (распознавание стоп-слов живо).
- Аборт: `abort_event` поддерживается в TTS и плеере.
- `_fix_encoding` не должен перекодировать уже валидный UTF-8 из Vosk.
- Частые причины «ассистент не остановился» — стоп-слова и кодировка (см. `_fix_encoding` в `lib/stt/transcription_worker.py`).
- `_fix_encoding` вынесен в `lib/stt/encoding.py` (worker ≤ лимита строк §9); имя `transcription_worker._fix_encoding` сохранено как алиас — тесты мокют его именно там.
- Ещё одна причина «ассистент молчит в ответ» — шлюз записи §4.6: с колонок играет медиа, и микрофон заглушён намеренно.

## 7. LLM-провайдеры
- Активный провайдер: `race` (OmniRouter + LM Studio, первый непустой ответ). Конфиг в `providers.json`, клиенты в `lib/providers/`.

## 8. Стиль и тестирование
- Тесты только в `tests/` (зеркало структуры `lib/`); внешние зависимости мокать (`pytest-mock`).
- В `except Exception` молчать запрещено: логировать через `swallowed()` из `lib/core/errors.py` (для OAuth-сбоев сам добавит подсказку про `reauth.py`); намеренная глухота — только с меткой `# blind-ok` (pre-commit блокирует новые молчаливые места, старые — baseline).
- Новый файл сразу держать ≤200 строк (лимит хука, §9) — проще вынести миксины/фабрики, чем урезать потом.

## 9. Версии и git-хуки
- `VERSION` — семантическая версия (major.minor.patch); `lib/__init__.py::__version__` держит ту же. Синхронизация — `scripts/bump_version.py patch|minor|major`.
- `.git/hooks/pre-commit` (при коммите выполняются ВСЕ проверки, порядок важен; упал — коммит не создан):
  1. `python -m pytest tests/ -q`;
  2. `python scripts/generate_commands_md.py --check` — актуальность COMMANDS.md;
  3. `flake8 --max-line-length=100 --exclude=...` (та же команда, что в §3);
  4. `python scripts/check_blind_except.py --git` — новые `except Exception` обязаны логировать (print/лог/raise/`swallowed()`/`# blind-ok`), сравнение с HEAD;
  5. `python scripts/check_lengths.py --git` — **лимит 200 строк** у каждого файла (py/ps1/bat);
  6. `python scripts/check_tooltips.py --git` — **каждый новый файл обязан иметь описание в `.structure.json`**;
  7. `python scripts/generate_structure.py --check` — STRUCTURE.md должен быть регенерирован.
- Если хук упал: для (4) — заменить глухой `except` на `swallowed(...)` (или `# blind-ok`); для (5) — урезать/разбить файл; для (6)+(7) — добавить строку в `.structure.json` и выполнить `python scripts/generate_structure.py --write`, затем пере-`git add`.
- `.git/hooks/post-commit` сам делает bump (patch) и коммит «Bump version to …» через `--no-verify` (чтобы не было цикла); bump-коммиты агент вручную не создаёт. После bump хук озвучивает завершение разработки (`scripts/announce_done.py`, §1) — ошибку озвучки глотает, на коммит не влияет.

## 10. Концепция голосовых команд (commands.json) — ЕДИНСТВЕННО ВЕРНАЯ

Первый уровень обработки — `commands.json`. Вся распознанная речь — это **поток строк** (каждый законченный фрагмент STT = строка).

Обозначения:
- `[ключ]` — ключевое слово: триггер из `triggers` (`алиса`, `пожалуйста`).
- `_команда_` — слово/словосочетание, указывающее на действие (шаблоны из `match`).
- `{настройка}` — слово/словосочетание, определяющее параметр команды (после команды).

Правила поиска команды:
1. Ключ может стоять **где угодно** в потоке — до или после команды.
2. Команда — слово/словосочетание **сразу перед ключом или сразу после ключа**.
3. Команда определяется по **максимальному совпадению ≥ 90%** с match-шаблоном. **Не угадывать**: пользователь должен правильно произносить команды; ниже порога — мимо (ложный вызов).
4. Слова, идущие **дальше после команды** — настройки для неё.
5. Для поиска команды/настроек смотрим **три строки** потока: строка над ключом, строка с ключом, строка после ключа.
6. **Ждём следующую строку** и ищем команду в ней только когда в строке ключа **одни триггеры** (пустое «ядро»: «алиса»/«пожалуйста» и больше ничего). Если слова есть, но совпадение < 90% — **не ждём**: уходим к decision-слою Laya (§4.2) — STT коверкает фразы («открой я туб» вместо «открой ютуб»), и Laya такие варианты ловит.
7. Если вокруг и рядом с ключом команд нет — **ложный вызов, игнорируем**.

Настройки (текущий набор):
- громче/тише: `{немного}` — уменьшить шаг в 2 раза; `{сильно}` — увеличить шаг в 2 раза (база 6% → 12%).

Трассировка этапов печатается в консоль: `[Command] …` (match по commands.json) → `[Decision] Лайя: команда распознана «…» (c=…)` / `команда не распознана (запрос в OmniRouter заглушён, пропускаем)`.

Это уровень 1. Дальше — decision-слой Laya (§4.2), legacy intent и фолбэк opencode; их поведение зафиксировано тестами `tests/core/test_laya_decision.py`, `tests/core/test_orchestrator_intent.py`, `tests/core/test_orchestrator_fallback.py`.