# TOOLTIP: Тесты молчаливой озвучки: без звука нет эхо-окна, проглоченные строки видны в логе
"""Молчаливая озвучка не должна глушить микрофон (§4.14 + §6).

Отдельный файл рядом с `test_orchestrator_speech.py`: тот ровно на лимите
200 строк (§9), а проверка держит поведение, которого в том файле нет.
"""
import time

from lib.core.orchestrator import Orchestrator


def make_orch(mocker, audible: bool):
    """Оркестратор с мок-зависимостями и готовым вердиктом «слышно было»."""
    tts = mocker.MagicMock()
    tts.audible = audible
    orch = Orchestrator(matcher=mocker.MagicMock(), output=mocker.MagicMock(),
                        tts=tts, suppress_after=0.5)
    orch._matcher.find_command.return_value = (None, [])
    orch._matcher.missing_requires.return_value = []
    orch._matcher.triggers = ["пожалуйста", "алиса"]
    orch._matcher.status_snapshot.return_value = {}
    orch._matcher.requires_map.return_value = {}
    return orch


class TestSilentPhraseDoesNotSuppress:
    """Окно эхо-затишья — только после реально звучавшей фразы."""

    def test_silent_finish_leaves_no_echo_window(self, mocker):
        """Звука не было — `_suppress_until` не двигаем, микрофон жив."""
        orch = make_orch(mocker, audible=False)
        orch._suppress_until = 0.0
        orch._speaking = True
        orch._on_speaking_finished()
        assert orch.speaking is False
        assert orch.suppress_until == 0.0

    def test_audible_finish_still_sets_the_window(self, mocker):
        """Регресс в другую сторону: с колонок (или в наушниках) эхо ловим."""
        orch = make_orch(mocker, audible=True)
        orch._speaking = True
        orch._on_speaking_finished()
        assert orch.suppress_until >= time.monotonic()

    def test_command_after_silent_phrase_is_executed(self, mocker):
        """Строка распознавания после молчаливой фразы остаётся командой."""
        orch = make_orch(mocker, audible=False)
        orch._suppress_until = 0.0
        orch._on_speaking_finished()
        orch._matcher.find_command.return_value = ("playpause", [])
        orch._matcher.has_trigger.return_value = True
        orch._matcher.execute_by_id.return_value = True
        orch.process_text("алиса пауза")
        orch._matcher.execute_by_id.assert_called_once_with("playpause")

    def test_tts_without_audible_flag_still_suppresses(self, mocker):
        """Fail-open: у самодельного tts флага нет — окно ставим как раньше."""
        class OldTts:
            def speak_and_play(self, *args, **kwargs):
                pass

        orch = Orchestrator(matcher=mocker.MagicMock(),
                            output=mocker.MagicMock(), tts=OldTts(),
                            suppress_after=0.5)
        orch._suppress_until = 0.0
        orch._on_speaking_finished()
        assert orch.suppress_until > 0.0


class TestSilentDropsAreLogged:
    """Проглоченная строка остаётся в логе: «не сказала» ≠ «не услышала».

    Раньше обе ветки молча выходили из `process_text`, и в разборе паузы
    команды нельзя было отличить от потерянной реплики пользователя.
    """

    def test_line_during_speech_is_logged(self, mocker):
        """Не стоп-слово во время озвучки — в лог, команда не выполняется."""
        orch = make_orch(mocker, audible=True)
        orch._speaking = True
        orch.process_text("алиса быстрее")
        assert "алиса быстрее" in orch._output.print_debug.call_args.args[0]
        orch._matcher.execute_by_id.assert_not_called()

    def test_stop_word_during_speech_is_not_a_drop(self, mocker):
        """Стоп-слово озвучку прерывает — записывать его как потерю не нужно."""
        orch = make_orch(mocker, audible=True)
        orch._speaking = True
        orch.process_text("стоп")
        orch._output.print_debug.assert_not_called()

    def test_line_in_echo_window_is_logged(self, mocker):
        """Эхо собственной фразы тоже видно: иначе лог обрывается на пустоте."""
        orch = make_orch(mocker, audible=True)
        orch._suppress_until = time.monotonic() + 5
        orch.process_text("алиса быстрее")
        assert "затишье" in orch._output.print_debug.call_args.args[0]
