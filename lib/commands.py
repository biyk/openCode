import json
import os
import platform
import subprocess
from difflib import SequenceMatcher
from typing import Optional

from lib.status import StatusStore
from lib.tts import TextToSpeech

CONFIRMATION_PHRASE = os.environ.get("VOICE_CONFIRMATION_PHRASE")

DEFAULT_TRIGGERS = ["пожалуйста", "алиса"]

# Порог максимального совпадения команды с match-шаблоном (не угадывать).
MATCH_THRESHOLD = 0.9


def _normalize(text: str) -> str:
    """Нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(text.lower().replace("ё", "е").split())


def _similarity(a: str, b: str) -> float:
    """Сходство двух строк (0.0–1.0) через SequenceMatcher."""
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _fmt_number(value: float) -> str:
    """Форматирует число для подстановки в shell-команду."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


class CommandMatcher:
    """Сопоставление голосовых команд с shell-командами.

    Каждая команда может требовать статусы ("requires": {"id": [...]}):
    команда выполняется только если все её статусы активны в StatusStore.
    Составные команды описываются в "sequences": {"id": {"steps": [...]}},
    после успешного шага выставляются его "provides"-статусы.
    """

    def __init__(self, commands_file: str,
                 status_store: Optional[StatusStore] = None):
        self._commands_file = commands_file
        self._mtime = 0.0
        self._data = self._load()
        self._tts = TextToSpeech()
        self._status_store = status_store

    def _load(self) -> dict:
        try:
            with open(self._commands_file, "r", encoding="utf-8") as f:
                self._data = json.load(f)
            self._mtime = os.path.getmtime(self._commands_file)
        except Exception:
            self._data = {}
        return self._data

    def reload(self) -> None:
        """Перечитывает файл команд, если он изменился с момента последней загрузки."""
        try:
            mtime = os.path.getmtime(self._commands_file)
        except OSError:
            return
        if mtime == self._mtime:
            return
        self._load()

    @property
    def triggers(self) -> list[str]:
        """Список триггеров для активации команд/LLM."""
        return self._data.get("triggers", DEFAULT_TRIGGERS)

    def has_trigger(self, text: str) -> bool:
        """Проверяет наличие любого триггера в тексте (case-insensitive)."""
        text_lower = text.lower()
        return any(t in text_lower for t in self.triggers)

    def _get_command(self, cmd_id: str,
                     settings: tuple[str, ...] = ()) -> Optional[str]:
        """Возвращает команду с учётом платформы и настроек.

        Настройки {немного}/{сильно} меняют числовые параметры
        (например {{step}}): множитель из секции "settings".
        """
        commands = self._data.get("commands", {})
        cmd = commands.get(cmd_id)
        if cmd is None:
            return None
        if not isinstance(cmd, dict):
            return cmd
        system = platform.system().lower()
        template = cmd.get(system) or cmd.get("default")
        if template is None:
            return None
        params = {}
        for key, value in cmd.items():
            if key in ("linux", "windows", "darwin", "default"):
                continue
            if isinstance(value, dict):
                value = value.get(system) or value.get("default")
            if isinstance(value, (int, float)):
                params[key] = value
        for word in settings:
            mults = self.settings_for(cmd_id).get(word, {})
            for param, factor in mults.items():
                if param in params and isinstance(factor, (int, float)):
                    params[param] = params[param] * factor
        for name, value in params.items():
            token = "{{" + name + "}}"
            if token in template:
                template = template.replace(token, _fmt_number(value))
        return template

    def core_phrase(self, text: str) -> str:
        """Возвращает текст без триггерных слов (нормализованный).

        «алиса включи ютуб пожалуйста» → «включи ютуб».
        """
        self.reload()
        triggers = {_normalize(t) for t in self.triggers}
        tokens = [t for t in _normalize(text).split(" ") if t not in triggers]
        return " ".join(tokens)

    def _match_command(self, core: str) -> tuple[Optional[str], list[str], float]:
        """Ищет команду в кандидате-строке (без ключа).

        Команда — префикс строки (макс. совпадение ≥ MATCH_THRESHOLD
        с match-шаблоном). Слова после команды — настройки.
        Возвращает (cmd_id, настройки, оценка совпадения).
        """
        tokens = _normalize(core).split()
        if not tokens:
            return None, [], 0.0
        best_id = None
        best_score = 0.0
        best_len = 0
        for cmd_id, templates in self._data.get("match", {}).items():
            for template in templates:
                t_tokens = _normalize(template).split()
                n = len(t_tokens)
                if n == 0 or n > len(tokens):
                    continue
                phrase = " ".join(tokens[:n])
                score = _similarity(phrase, template)
                if score >= MATCH_THRESHOLD and (
                        score > best_score
                        or (score == best_score and n > best_len)):
                    best_id = cmd_id
                    best_score = score
                    best_len = n
        if best_id is None:
            return None, [], 0.0
        return best_id, tokens[best_len:], best_score

    def find_command(self, window: list[str]) -> tuple[Optional[str], list[str], bool]:
        """Поиск команды уровня commands.json по концепции трёх строк.

        window — последние строки потока (по порядку поступления).
        Возвращает (cmd_id, настройки, wait):
          - wait=True → в последней строке ключ, команды пока нет:
            ждём следующую строку ввода и ищем команду в ней;
          - cmd_id не None → команда найдена (настройки собраны);
          - (None, [], False) → ложный вызов: вокруг ключа команд нет.
        """
        self.reload()
        window = [_normalize(w) for w in window]
        key_idx = None
        for i, line in enumerate(window):
            if self.has_trigger(line):
                key_idx = i
        if key_idx is None:
            return None, [], False
        candidates = [(0, self.core_phrase(window[key_idx]))]
        if key_idx > 0:
            candidates.append((-1, self.core_phrase(window[key_idx - 1])))
        if key_idx < len(window) - 1:
            candidates.append((1, self.core_phrase(window[key_idx + 1])))
        best_match = None  # (пишк score, порядок приоритета, cmd_id, settings)
        for pos, cand in candidates:
            if not cand.strip():
                continue
            cmd_id, settings, score = self._match_command(cand)
            if cmd_id is None:
                continue
            candidate = (score, -abs(pos), cmd_id, settings)
            if best_match is None or candidate[:2] > best_match[:2]:
                best_match = candidate
        if best_match is not None:
            return best_match[2], best_match[3], False
        if key_idx >= len(window) - 1:
            return None, [], True
        return None, [], False

    def settings_for(self, cmd_id: str) -> dict:
        """Возвращает секцию настроек команды {"слово": {"param": множитель}}."""
        return self._data.get("settings", {}).get(cmd_id, {})

    def find_literal_id(self, text: str) -> Optional[str]:
        """Возвращает id команды при ДОСЛОВНОМ совпадении (или None).

        Ядро фразы (текст без триггеров) должно в точности равняться
        одному из шаблонов. Подстроки НЕ считаются: «включи пожалуйста»
        не запускает playpause по шаблону «включи». Статусы здесь
        не проверяются — их смотрит вызывающий через missing_requires().
        """
        self.reload()
        if not self.has_trigger(text):
            return None
        core = self.core_phrase(text)
        if not core:
            return None
        for cmd_id, templates in self._data.get("match", {}).items():
            for template in templates:
                if _normalize(template) == core:
                    return cmd_id
        return None

    def get_command(self, cmd_id: str,
                    settings: tuple[str, ...] = ()) -> Optional[str]:
        """Возвращает shell-команду по id с учётом платформы."""
        self.reload()
        return self._get_command(cmd_id, settings)

    def execute_by_id(self, cmd_id: str,
                      settings: tuple[str, ...] = ()) -> bool:
        """Выполняет команду по id (или составную sequence по шагам)."""
        self.reload()
        seq = self.sequences().get(cmd_id)
        if seq is not None:
            return self._execute_sequence(cmd_id, seq, settings)
        return self._execute_step(cmd_id, settings)

    def _execute_step(self, cmd_id: str,
                      settings: tuple[str, ...] = ()) -> bool:
        """Выполняет один шаг: проверка requires, shell, provides."""
        if self.missing_requires(cmd_id):
            return False
        command = self._get_command(cmd_id, settings)
        if not command:
            return False
        if not self._run(command):
            return False
        self._mark_provides(cmd_id)
        return True

    def _execute_sequence(self, seq_id: str, seq: dict,
                          settings: tuple[str, ...] = ()) -> bool:
        """Выполняет шаги составной команды по очереди до первой ошибки."""
        if self.missing_requires(seq_id):
            return False
        for step in seq.get("steps", []):
            if not self._execute_step(step, settings):
                return False
        self._mark_provides(seq_id)
        return True

    def _mark_provides(self, cmd_id: str) -> None:
        """Оптимистично выставляет provides-статусы после успеха."""
        if self._status_store is None:
            return
        for name in self.provides_for(cmd_id):
            self._status_store.set(name, True)

    def _run(self, command: str) -> bool:
        """Запускает shell-команду и возвращает успех."""
        try:
            subprocess.run(command, shell=True, check=True)
            if os.environ.get("VOICE_CONFIRMATION_PHRASE"):
                self._tts.speak_and_play(os.environ["VOICE_CONFIRMATION_PHRASE"])
            return True
        except subprocess.CalledProcessError:
            return False

    def get_llm_config(self) -> dict:
        """Возвращает конфигурацию для LLM."""
        return self._data.get("llm", {})

    def get_intent_config(self) -> dict:
        """Возвращает конфигурацию интеллектуального классификатора команд."""
        return self._data.get("intent", {})

    def match_config(self) -> dict:
        """Возвращает словарь {command_id: [фразы]} для классификатора."""
        return self._data.get("match", {})

    def get_skills_config(self) -> dict:
        """Возвращает конфигурацию скиллов."""
        return self._data.get("skills", {})

    def get_opencode_cli_config(self) -> dict:
        """Возвращает конфигурацию фолбэка в console opencode."""
        return self._data.get("opencode_cli", {})

    def get_google_config(self) -> dict:
        """Возвращает конфигурацию интеграции Google (calendar/tasks)."""
        return self._data.get("google", {})

    def requires_map(self) -> dict:
        """Возвращает {command_id: [статусы]} — условия запуска команд."""
        return self._data.get("requires", {})

    def provides_map(self) -> dict:
        """Возвращает {command_id: [статусы]} — статусы после успеха."""
        return self._data.get("provides", {})

    def sequences(self) -> dict:
        """Возвращает {sequence_id: {steps: [...]}} составных команд."""
        return self._data.get("sequences", {})

    def requires_for(self, cmd_id: str) -> list[str]:
        """Возвращает статусы, требуемые для запуска команды."""
        requires = self.requires_map().get(cmd_id, [])
        return list(requires)

    def provides_for(self, cmd_id: str) -> list[str]:
        """Возвращает статусы, выставляемые после успеха команды."""
        provides = self.provides_map().get(cmd_id, [])
        return list(provides)

    def missing_requires(self, cmd_id: str) -> list[str]:
        """Возвращает невыполненные requires команды (пусто = можно)."""
        if self._status_store is None or not self._status_store.enabled:
            return []
        return self._status_store.ensure(self.requires_for(cmd_id))

    def need_message(self, name: str) -> str:
        """Человекочитаемое сообщение при отсутствии статуса."""
        if self._status_store is not None:
            return self._status_store.need_message(name)
        return f"Нужен статус: {name}"

    def status_snapshot(self) -> dict[str, bool]:
        """Текущие статусы (пусто, если хранилище не подключено)."""
        if self._status_store is None:
            return {}
        return self._status_store.snapshot()
