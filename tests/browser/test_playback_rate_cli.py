# TOOLTIP: Тесты CLI скорости воспроизведения и проводки команд rateup/ratedown
"""Тесты CLI lib/browser/playback_rate.py и проводки новых команд.

Здесь аргументы, коды возврата и озвучка итога, плюс проверка, что
`rateup`/`ratedown` из конфига устройства идут в этот CLI и не отнимают
«громче»/«тише» у команд громкости.
"""

import platform

import pytest

from lib.browser import playback_rate as pr


class TestParseArgs:
    """`up|down [шаг]`: шаг из commands.json, запятая тоже принимается."""

    def test_valid(self):
        assert pr.parse_args(["up", "0.05"]) == ("up", 0.05)
        assert pr.parse_args(["down", "0,05"]) == ("down", 0.05)
        assert pr.parse_args(["up"]) == ("up", pr.STEP_DEFAULT)

    def test_invalid(self):
        for bad in (["вперёд"], ["up", "abc"], ["up", "0"], []):
            assert pr.parse_args(bad)[0] is None


class TestMain:
    """Коды возврата и озвучка: результат слышен, а не только в консоли."""

    def test_success_chooses_direction_phrase(self, mocker):
        """Успех — озвучка направления, код 0, дельта по action."""
        mocker.patch.object(pr, "bump_rate", return_value={"ok": True})
        speak = mocker.patch.object(pr, "_speak")
        assert pr.main(["up", "0.05"]) == 0
        pr.bump_rate.assert_called_once_with(0.05)
        speak.assert_called_once_with(pr.PHRASES["up"])

    def test_down_passes_negative_delta(self, mocker):
        """down — отрицательная дельта того же шага."""
        mocker.patch.object(pr, "bump_rate", return_value={"ok": True})
        mocker.patch.object(pr, "_speak")
        assert pr.main(["down", "0.05"]) == 0
        pr.bump_rate.assert_called_once_with(-0.05)

    def test_silence_is_error_and_speaks_it(self, mocker):
        """Нечего крутить — код 1 и вслух «Ни одно видео не играет»."""
        mocker.patch.object(pr, "bump_rate",
                            return_value={"ok": False, "error": "x"})
        speak = mocker.patch.object(pr, "_speak")
        assert pr.main(["up"]) == 1
        speak.assert_called_once_with(pr.PHRASE_SILENCE)

    def test_dead_browser_speaks_its_own_phrase(self, mocker):
        """Вкладки не ответили — вслух «Браузер не отвечает», не «не играет»."""
        mocker.patch.object(pr, "bump_rate", return_value={
            "ok": False, "error": "вкладки не ответили (2)",
            "phrase": pr.PHRASE_DEAD})
        speak = mocker.patch.object(pr, "_speak")
        assert pr.main(["up"]) == 1
        speak.assert_called_once_with(pr.PHRASE_DEAD)

    def test_bad_args_no_browser(self, mocker):
        """Неверные аргументы — код 2, к браузеру не идём."""
        bump = mocker.patch.object(pr, "bump_rate")
        mocker.patch.object(pr, "_speak")
        assert pr.main(["вперёд"]) == 2
        bump.assert_not_called()

    def test_speak_failure_does_not_break_run(self, mocker):
        """Сбой TTS (нет модели) не отменяет уже выполненный сдвиг."""
        mocker.patch("lib.tts.TextToSpeech", side_effect=OSError("нет piper"))
        pr._speak("Быстрее")


class TestDeviceWiring:
    """Команды конфига устройства ведут в новый CLI, громкость не тронута."""

    @pytest.fixture
    def matcher(self):
        from lib.voice_cmd.commands import CommandMatcher
        from lib.voice_cmd.config_loader import get_device_commands_path
        return CommandMatcher(get_device_commands_path(platform.node()))

    @pytest.mark.parametrize("phrase,cmd,delta", [
        ("алиса быстрее", "rateup", "up"),
        ("алиса медленней", "ratedown", "down"),
        ("алиса ускорь видео", "rateup", "up"),
        ("алиса замедли", "ratedown", "down"),
    ])
    def test_phrase_renders_cli(self, matcher, phrase, cmd, delta):
        assert matcher.find_command(phrase)[0] == cmd
        shell = matcher.get_command(cmd)
        assert f"lib.browser.playback_rate {delta} 0.05" in shell

    def test_speech_volume_not_hijacked(self, matcher):
        """«громче»/«тише» остаются громкостью — скорость это другая команда."""
        assert matcher.find_command("алиса громче")[0] == "volumeup"
        assert matcher.find_command("алиса тише")[0] == "volumedown"

    def test_criteria_cover_both_directions(self, matcher):
        """Decision-слой знает обе команды и отделяет скорость от громкости."""
        criteria = matcher.get_decision_config().get("criteria", {})
        assert "rateup" in criteria and "ratedown" in criteria
        assert "громкость" in criteria["rateup"]
