"""Тесты ручного текстового ввода (альтернатива голосу).

Два слоя:
- TextInputs.run — читает stdin, игнорирует пустые строки, останавливается на
  «выход»/EOF, отключается без TTY;
- submit_manual_text — печатная команда не требует кодового слова:
  если триггера нет, в конец дописывается MANUAL_TRIGGER, и строка уходит в
  оркестратор уже «с ключом» (§10).
"""
import pytest

import lib.stt.text_inputs as ti_mod
import lib.stt.transcription_worker as worker_mod
from lib.stt.text_inputs import TextInputs


class TestTextInputsRun:
    """Цикл чтения stdin → on_text."""

    def _patch_tty(self, mocker, isatty=True):
        stdin = mocker.patch.object(ti_mod, "sys")
        stdin.stdin.isatty.return_value = isatty
        return stdin

    def test_dispatches_nonblank_lines(self, mocker):
        self._patch_tty(mocker)
        on_text = mocker.MagicMock()
        mocker.patch("builtins.input", side_effect=["громче", "  ", "тише", EOFError])
        TextInputs(on_text, output=None).run()
        assert on_text.call_args_list == [mocker.call("громче"),
                                          mocker.call("тише")]

    def test_exit_word_stops_without_dispatch(self, mocker):
        self._patch_tty(mocker)
        on_text = mocker.MagicMock()
        mocker.patch("builtins.input",
                     side_effect=["выход", "не должен дойти", EOFError])
        TextInputs(on_text, output=None).run()
        on_text.assert_not_called()

    def test_eof_stops(self, mocker):
        self._patch_tty(mocker)
        on_text = mocker.MagicMock()
        mocker.patch("builtins.input", side_effect=EOFError)
        TextInputs(on_text, output=None).run()
        on_text.assert_not_called()

    def test_disabled_without_tty(self, mocker):
        self._patch_tty(mocker, isatty=False)
        on_text = mocker.MagicMock()
        output = mocker.MagicMock()
        TextInputs(on_text, output=output).run()
        on_text.assert_not_called()
        assert output.print_info.called


class TestSubmitManualText:
    """submit_manual_text дописывает триггер и гонит строку в оркестратор."""

    @pytest.fixture
    def worker(self, mocker):
        w = worker_mod.TranscriptionWorker.__new__(
            worker_mod.TranscriptionWorker)
        w._matcher = mocker.MagicMock()
        w._logger = mocker.MagicMock()
        w._accumulated = []
        w._processed = []
        w._orchestrator = mocker.MagicMock()
        w._orchestrator.process_text.side_effect = w._processed.append
        return w

    def test_trigger_appended_when_absent(self, worker, mocker):
        worker._matcher.has_trigger.return_value = False
        ti_mod.submit_manual_text(worker, "громче")
        assert worker._processed == ["громче " + ti_mod.MANUAL_TRIGGER]
        worker._logger.log_command.assert_called_once()

    def test_existing_trigger_kept(self, worker, mocker):
        worker._matcher.has_trigger.return_value = True
        ti_mod.submit_manual_text(worker, "алиса громче")
        assert worker._processed == ["алиса громче"]

    def test_blank_is_noop(self, worker, mocker):
        ti_mod.submit_manual_text(worker, "   ")
        assert worker._processed == []
        worker._logger.log_command.assert_not_called()
