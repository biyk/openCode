# TOOLTIP: Тесты: ответ на idle-вопрос дописывается ключом «начал» и идёт командой
"""Ответ на «чем занимаешься?» — команда taskstart, а не «просто фраза».

Вопрос фона задаётся с ключом команды (`ask(prefix=...)`), и строка-ответ
дописывается этим ключом («начал прогулка»), минуя требование триггера: так
она попадает и в скрипт (`python -m lib.task_start "прогулка"`), и на
остальные уровни (Laya/LLM), а в логе остаётся командой (§4.3).
Ключ не дописывается, если «голая» строка — другая команда: иначе «алиса
быстрее» уходила как «начал алиса быстрее», матчалась taskstart и терялась.
"""

import platform
import time

import pytest

from lib.core.task_pick import TASKSTART_CMD_ID, TASKSTART_KEY
from lib.core.orchestrator import Orchestrator


@pytest.fixture(scope="module")
def matcher():
    """Матчер конфига устройства: ключ обязан быть его шаблоном taskstart."""
    from lib.voice_cmd.commands import CommandMatcher
    from lib.voice_cmd.config_loader import get_device_commands_path
    return CommandMatcher(get_device_commands_path(platform.node()))


class TestTaskstartKeyMatchesConfig:
    """Ключ ответа — реальный шаблон команды, а не выдуманное слово."""

    def test_key_is_a_template(self, matcher):
        templates = [t.lower() for t in matcher.match_config().get(
            TASKSTART_CMD_ID, [])]
        if not templates:
            pytest.skip("конфиг устройства без taskstart")
        assert TASKSTART_KEY in templates

    def test_keyed_answer_is_the_command(self, matcher):
        """«начал прогулка» без обращения — команда с чистым названием."""
        if not matcher.match_config().get(TASKSTART_CMD_ID):
            pytest.skip("конфиг устройства без taskstart")
        cmd_id, settings = matcher.find_command(
            f"{TASKSTART_KEY} прогулка", require_trigger=False)
        assert cmd_id == TASKSTART_CMD_ID
        assert settings == ["прогулка"]

    def test_without_the_key_the_rule_stands(self, matcher):
        """Обычная речь без обращения по-прежнему не команда (§10)."""
        assert matcher.find_command("прогулка")[0] is None


def _make(mocker, **kwargs):
    """Оркестратор с мок-зависимостями, озвучкой и уровнями под контролем."""
    defaults = {"matcher": mocker.MagicMock(), "output": mocker.MagicMock(),
                "tts": mocker.MagicMock()}
    defaults.update(kwargs)
    orch = Orchestrator(**defaults)
    if "matcher" not in kwargs:
        orch._matcher.find_command.return_value = (None, [])
        orch._matcher.has_trigger.return_value = False
        orch._matcher.core_phrase.side_effect = lambda text: text
    mocker.patch.object(orch, "_say")
    levels = mocker.patch.object(orch, "_process_commands_level")
    levels.return_value = True
    return orch


class TestPrefixedQuestion:
    """Вопрос с ключом: ответ становится командой и идёт в уровни."""

    def test_answer_goes_to_levels_with_key(self, mocker):
        orch = _make(mocker)
        note = mocker.MagicMock()
        orch.ask("Чем ты сейчас занимаешься?", note, "task_idle",
                 prefix=TASKSTART_KEY)
        orch.process_text("прогулка")
        orch._process_commands_level.assert_called_once_with(
            f"{TASKSTART_KEY} прогулка", forced=True)
        assert orch._output.print_text.call_args.args[0] == (
            f"{TASKSTART_KEY} прогулка")
        note.assert_not_called()
        assert orch.pending_ask is None

    def test_key_not_duplicated(self, mocker):
        """Пользователь сам сказал «начал …» — второй ключ не нужен."""
        orch = _make(mocker)
        orch.ask("Вопрос?", mocker.MagicMock(), "task_idle",
                 prefix=TASKSTART_KEY)
        orch.process_text(f"{TASKSTART_KEY} прогулка")
        orch._process_commands_level.assert_called_once_with(
            f"{TASKSTART_KEY} прогулка", forced=True)

    def test_miss_falls_back_to_the_question(self, mocker):
        """Команда не прошла (такой задачи нет) — отвечает сам вопрос."""
        orch = _make(mocker)
        orch._process_commands_level.return_value = False
        note = mocker.MagicMock()
        orch.ask("Вопрос?", note, "task_idle", prefix=TASKSTART_KEY)
        orch.process_text("не знаю что")
        note.assert_called_once_with("не знаю что")

    def test_stop_word_is_not_a_command(self, mocker):
        """«стоп» снимает вопрос, а не превращается в «начал стоп»."""
        orch = _make(mocker)
        note = mocker.MagicMock()
        orch.ask("Вопрос?", note, "task_idle", prefix=TASKSTART_KEY)
        orch.process_text("стоп")
        orch._process_commands_level.assert_not_called()
        note.assert_not_called()
        assert orch.pending_ask is None

    def test_empty_answer_does_not_run_the_script(self, mocker):
        """Пустая строка — не команда: уровни не гоняем, колбэк решает."""
        orch = _make(mocker)
        note = mocker.MagicMock()
        orch.ask("Вопрос?", note, "task_idle", prefix=TASKSTART_KEY)
        orch.process_text("   ")
        orch._process_commands_level.assert_not_called()
        note.assert_called_once_with("   ")

    def test_expired_question_keeps_plain_pipeline(self, mocker):
        """Просроченный вопрос не дописывает ключ: строка — обычная речь."""
        orch = _make(mocker)
        note = mocker.MagicMock()
        orch.ask("Вопрос?", note, "task_idle", prefix=TASKSTART_KEY)
        orch._pending_ask.deadline = time.monotonic() - 1
        orch.process_text("привет")
        orch._process_commands_level.assert_called_once_with("привет")
        note.assert_not_called()

    def test_other_command_is_not_hijacked(self, mocker):
        """Регресс: «алиса быстрее» — команда, а не название задачи."""
        orch = _make(mocker)
        orch._matcher.find_command.side_effect = lambda text, **kw: (
            ("rateup", []) if text == "алиса быстрее" else (None, []))
        note = mocker.MagicMock()
        orch.ask("Чем ты сейчас занимаешься?", note, "task_idle",
                 prefix=TASKSTART_KEY)
        orch.process_text("алиса быстрее")
        orch._process_commands_level.assert_called_once_with("алиса быстрее")
        note.assert_not_called()
        assert orch.pending_ask == "task_idle"


def _make_real(mocker, cmd_id: str = TASKSTART_CMD_ID):
    """Оркестратор с настоящими уровнями: видно, что уходит в канал ответа."""
    orch = Orchestrator(matcher=mocker.MagicMock(),
                        output=mocker.MagicMock(), tts=mocker.MagicMock())
    m = orch._matcher
    m.find_command.return_value = (cmd_id, ["прогулка"])
    m.missing_requires.return_value = []
    m.execute_by_id.return_value = False
    mocker.patch.object(orch, "_speak_async")
    return orch


class TestAnswerMissSpeaksOnce:
    """Промах команды на ответе не должен озвучиваться дважды (§4.3)."""

    def test_channel_is_silent_on_forced_miss(self, mocker):
        """Уровень на forced молчит: говорит колбэк вопроса, а не уровень."""
        orch = _make_real(mocker)
        note = mocker.MagicMock()
        texts: list[str] = []
        orch.ask("Чем ты сейчас занимаешься?", note, "task_idle",
                 prefix=TASKSTART_KEY)
        orch.process_text("прогулка", reply=texts.append)
        assert texts == []
        note.assert_called_once_with("прогулка")

    def test_plain_request_still_answers_the_failure(self, mocker):
        """Обычный запрос (не ответ на вопрос) остаётся с ответом уровня."""
        orch = _make_real(mocker)
        texts: list[str] = []
        orch.process_text("начал прогулку", reply=texts.append)
        assert texts == ["Такой задачи в списке нет"]


class TestPlainQuestionUnchanged:
    """Вопрос без ключа живёт как раньше: строку собирает колбэк."""

    def test_note_answer_is_not_a_command(self, mocker):
        orch = _make(mocker)
        note = mocker.MagicMock()
        orch.ask("Всё ли в порядке?", note, "rest")
        orch.process_text("да")
        note.assert_called_once_with("да")
        orch._process_commands_level.assert_not_called()
        assert orch._output.print_text.call_args.args[0] == "да"
