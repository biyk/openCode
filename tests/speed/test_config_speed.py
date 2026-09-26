"""Скорость конфиг-слоя: то, что уже кэшируется по mtime.

Базовый уровень: команды и алиасы перечитываются только при изменении
файла. Замеряем, что эти пути действительно дешёвые в горячем цикле —
иначе оптимизации ниже (статусы, Laya, LLM) искать бессмысленно.
"""

import platform

from lib.voice_cmd.aliases import AliasStore
from lib.voice_cmd.commands import CommandMatcher
from lib.voice_cmd.config_loader import get_device_commands_path


def _commands_file() -> str:
    return get_device_commands_path(platform.node())


class TestConfigSpeed:
    """Загрузка/переиспользование commands.json и aliases.json."""

    def test_matcher_init(self, bench):
        """Полная инициализация матчера (json + TextToSpeech)."""
        path = _commands_file()
        bench.record("config.matcher_init",
                     lambda: CommandMatcher(path), runs=3)

    def test_reload_noop(self, bench):
        """reload() при неизменном файле: только getmtime."""
        matcher = CommandMatcher(_commands_file())
        bench.record("config.reload_noop", matcher.reload, runs=50)

    def test_find_command_hit(self, bench):
        """Поиск команды уровня commands.json по фразе с триггером."""
        matcher = CommandMatcher(_commands_file())
        bench.record("config.find_command",
                     lambda: matcher.find_command(
                         ["алиса выключи музыку"]), runs=20)

    def test_find_command_miss(self, bench):
        """Промах по порогу 90% (худший случай: перебор всех шаблонов)."""
        matcher = CommandMatcher(_commands_file())
        bench.record("config.find_command_miss",
                     lambda: matcher.find_command(
                         ["алиса совершенно не команда вот прям совсем"]),
                     runs=20)

    def test_alias_resolve(self, bench):
        """AliasStore.resolve: reload(noop) + поиск по нормализации."""
        store = AliasStore(
            AliasStore.path_for_commands_file(_commands_file()))
        bench.record("aliases.resolve",
                     lambda: store.resolve("алиса открой я туб"), runs=50)
