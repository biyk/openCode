"""Интеграция STT→команда: сквозной путь сквозь worker.run().

Мокнуты только внешний мир: Vosk (KaldiRecognizer), микрофон (sounddevice)
и исполнение shell (subprocess.run). Всё между ними — реальный
TranscriptionWorker-каркас, настоящий Orchestrator и настоящий CommandMatcher
с реальным commands.json. Так проверяется сама склейка звеньев, а не то,
что заглушка что-то вернула.

Покрываем ветки конфига (§10): базовый матч, настройки {сильно}, ключ после
команды, правило «ждём следующую строку» (команда в строке после ключа),
свободный текст {{text}}, sequence по шагам, ложный вызов, стоп-слово в речи.
"""
import json
import os
import tempfile

import pytest

import lib.stt.transcription_worker as worker_mod
from lib.voice_cmd.commands import CommandMatcher
from lib.core.orchestrator import Orchestrator


@pytest.fixture
def commands_file():
    """Временный commands.json с командами под каждый проверяемый кейс."""
    cfg = {
        "triggers": ["пожалуйста", "алиса"],
        "commands": {
            "volumeup": {"default": "echo volumeup {{step}}", "step": 6},
            "openyoutube": {"default": "echo openyoutube"},
            "youtube_news": {"default": "echo youtube_news"},
            "stop": {"default": "echo stop"},
            "task-add": {"default": "echo task-add {{text}}"},
        },
        "match": {
            "volumeup": ["громче", "сделай громче"],
            "openyoutube": ["открой ютуб"],
            "youtube_news": ["новости ютуб"],
            "stop": ["стоп", "остановить", "выключи"],
            "task-add": ["поставь задачу", "добавь задачу"],
            "news": ["включи новости", "покажи новости"],
        },
        "settings": {
            "volumeup": {"немного": {"step": 0.5}, "сильно": {"step": 2.0}},
        },
        "sequences": {
            "news": {"steps": ["openyoutube", "youtube_news"]},
        },
    }
    path = tempfile.mktemp(suffix=".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestSttToCommandIntegration:
    """Речь на входе worker.run() → исполненная shell-команда на выходе."""

    def _make_worker(self, mocker, commands_file):
        """Собирает worker с настоящим матчером и оркестратором."""
        matcher = CommandMatcher(commands_file)  # без status_store: не блокируется
        worker = worker_mod.TranscriptionWorker.__new__(
            worker_mod.TranscriptionWorker)
        worker.lang_code = "ru"
        worker._running = mocker.MagicMock()
        worker._queue = mocker.MagicMock()
        worker._accumulated = []
        worker._output = mocker.MagicMock()
        worker._logger = mocker.MagicMock()
        worker._matcher = matcher
        worker._llm = mocker.MagicMock()
        worker._tts = mocker.MagicMock()
        worker._orchestrator = Orchestrator(
            matcher=matcher, output=worker._output, tts=worker._tts)
        return worker

    def _patch_env(self, mocker):
        """Глушит Vosk/микрофон; возвращает recorder исполненных shell-команд."""
        mocker.patch.object(worker_mod, "_fix_encoding",
                            side_effect=lambda x: x)
        mocker.patch.object(worker_mod, "SetLogLevel")
        mocker.patch("lib.stt.vosk_model.ensure_vosk_model",
                     return_value="model")
        mocker.patch.object(worker_mod, "Model")
        mocker.patch.object(worker_mod, "KaldiRecognizer")
        mocker.patch("lib.stt.transcription_worker.sd.RawInputStream",
                     return_value=mocker.MagicMock())
        run = mocker.patch("lib.voice_cmd.commands.subprocess.run",
                           return_value=mocker.MagicMock())
        return run

    def _run_chain(self, mocker, commands_file, phrases):
        """Полный прогон run(): возвращает список исполненных shell-команд.

        Каждая фраза — один блок аудио, который Vosk (мок) выдаёт готовой
        строкой; цикл worker'а сам гонит её в реальный оркестратор.
        """
        worker = self._make_worker(mocker, commands_file)
        run = self._patch_env(mocker)
        rec = mocker.MagicMock()
        rec.AcceptWaveform.return_value = True
        rec.Result.side_effect = [
            json.dumps({"text": p}) for p in phrases]
        rec.FinalResult.return_value = '{"text": ""}'
        mocker.patch.object(worker_mod, "KaldiRecognizer",
                            return_value=rec)
        # is_set: True на каждую фразу + одна False для выхода из цикла.
        worker._running.is_set.side_effect = [True] * len(phrases) + [False]
        worker._queue.get.side_effect = [b"audio"] * len(phrases)
        worker.run()
        return [call.args[0] for call in run.call_args_list]

    def test_simple_command_opens_youtube(self, mocker, commands_file):
        """«алиса открой ютуб» → исполняется shell openyoutube."""
        executed = self._run_chain(mocker, commands_file,
                                   ["алиса открой ютуб"])
        assert executed == ["echo openyoutube"]

    def test_setting_silno_doubles_step(self, mocker, commands_file):
        """{сильно} доходит до execute: шаг громкости удваивается 6→12."""
        executed = self._run_chain(
            mocker, commands_file, ["пожалуйста сделай громче сильно"])
        assert executed == ["echo volumeup 12"]

    def test_key_after_command_matches(self, mocker, commands_file):
        """Ключ может стоять после команды: «громче пожалуйста»."""
        executed = self._run_chain(
            mocker, commands_file, ["сделай громче пожалуйста"])
        assert executed == ["echo volumeup 6"]

    def test_command_on_line_after_bare_key(self, mocker, commands_file):
        """Пустое ядро ключа → ждём строку: команда находится в следующей."""
        executed = self._run_chain(
            mocker, commands_file,
            ["алиса", "выключи"])
        assert executed == ["echo stop"]

    def test_free_text_goes_into_command(self, mocker, commands_file):
        """{{text}} собирает название задачи после команды."""
        executed = self._run_chain(
            mocker, commands_file,
            ["алиса поставь задачу приготовить гречку"])
        assert executed == ["echo task-add приготовить гречку"]

    def test_sequence_runs_steps_in_order(self, mocker, commands_file):
        """Sequence news раскрывается в два шага по порядку."""
        executed = self._run_chain(
            mocker, commands_file, ["алиса включи новости"])
        assert executed == ["echo openyoutube", "echo youtube_news"]

    def test_no_trigger_nothing_executed(self, mocker, commands_file):
        """«привет мир» без ключа — ложный вызов, ничего не исполняется."""
        executed = self._run_chain(mocker, commands_file, ["привет мир"])
        assert executed == []
