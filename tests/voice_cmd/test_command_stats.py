"""Тесты статистики использования команд (CommandStats + хук матчера).

Тестируем: счётчик по cmd_id с first/last_seen, fail-open на чтении/записи,
 отчёт (известные id commands.json + sequences, сортировка по частоте) и
 главное — что успешный execute_by_id помечает команду, а неудачный нет.
"""

import json
import os
import subprocess
from datetime import datetime

import pytest

from lib.voice_cmd.command_stats import (
    CommandStats,
    build_report,
    known_ids,
    stats_path_for,
)
from lib.voice_cmd.commands import CommandMatcher, DEFAULT_TRIGGERS

STATS = "command_stats.json"


def _write_commands(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def commands(tmp_path):
    """commands.json с обычной командой, sequence и описаниями в tmp_path."""
    data = {
        "triggers": DEFAULT_TRIGGERS,
        "commands": {
            "volumeup": {"windows": "echo up", "default": "echo up"},
            "rare": {"default": "echo rare"},
            "dead": {"default": "echo dead"},
        },
        "sequences": {"combo": {"steps": ["volumeup"]}},
        "descriptions": {"volumeup": "громче", "dead": "мёртвая"},
        "match": {"volumeup": ["громче"]},
    }
    file = tmp_path / "commands.json"
    _write_commands(file, data)
    return file


class TestStatsPath:
    def test_derived_from_commands_dir(self):
        assert stats_path_for("/x/targets/host/commands.json") == os.path.join(
            "/x/targets/host", STATS)


class TestCommandStats:
    def test_bump_creates_and_increments(self, tmp_path):
        stats = CommandStats(str(tmp_path / STATS))
        stats.bump("openyoutube", when=datetime(2026, 1, 1, 10, 0, 0))
        stats.bump("openyoutube", when=datetime(2026, 1, 2, 11, 0, 0))
        entry = stats.snapshot()["openyoutube"]
        assert entry["count"] == 2
        assert entry["first_seen"].startswith("2026-01-01")
        assert entry["last_seen"].startswith("2026-01-02")

    def test_snapshot_missing_is_empty(self, tmp_path):
        assert CommandStats(str(tmp_path / "nope.json")).snapshot() == {}

    def test_bump_ignores_empty_id(self, tmp_path):
        stats = CommandStats(str(tmp_path / STATS))
        stats.bump("")
        assert stats.snapshot() == {}

    def test_corrupt_file_recovers_on_bump(self, tmp_path):
        path = tmp_path / STATS
        path.write_text("{не json", encoding="utf-8")
        stats = CommandStats(str(path))
        assert stats.snapshot() == {}          # fail-open на чтении
        stats.bump("vol")                        # перезапись валидным JSON
        assert stats.snapshot()["vol"]["count"] == 1

    def test_write_failure_is_swallowed(self, tmp_path, mocker):
        stats = CommandStats(str(tmp_path / STATS))
        mocker.patch("lib.voice_cmd.command_stats.os.replace",
                     side_effect=OSError("disk full"))
        stats.bump("vol")                        # не бросает наружу
        assert not (tmp_path / STATS).exists()

    def test_garbage_count_treated_as_zero(self, tmp_path):
        path = tmp_path / STATS
        path.write_text(json.dumps({"vol": {"count": "abc"}}), encoding="utf-8")
        stats = CommandStats(str(path))
        stats.bump("vol")
        assert stats.snapshot()["vol"]["count"] == 1


class TestReport:
    def test_known_ids_unions_commands_and_sequences(self, commands):
        data = json.loads(commands.read_text(encoding="utf-8"))
        assert known_ids(data) == {"volumeup", "rare", "dead", "combo"}

    def test_report_sorted_with_never_used_first(self, commands):
        stats_path = stats_path_for(str(commands))
        CommandStats(stats_path).bump("volumeup")
        CommandStats(stats_path).bump("volumeup")
        CommandStats(stats_path).bump("combo")
        rows = build_report(str(commands))
        counts = [row[0] for row in rows]
        assert counts == sorted(counts)              # по возрастанию
        assert rows[0][0] == 0                        # «мёртвая» сверху
        assert {row[2] for row in rows} == {
            "volumeup", "rare", "dead", "combo"}
        dead = next(r for r in rows if r[2] == "dead")
        assert dead[3] == "мёртвая"                   # описание подтянуто


class TestMatcherHook:
    """Главное: успешный execute_by_id пишет в статистику, неудачный — нет."""

    def _matcher(self, commands, mocker):
        mocker.patch("lib.voice_cmd.commands.platform.system",
                     return_value="Windows")
        return CommandMatcher(str(commands))

    def test_success_bumps_stats(self, commands, mocker):
        run = self._matcher(commands, mocker)
        stats_file = stats_path_for(str(commands))
        if os.path.exists(stats_file):
            os.unlink(stats_file)
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        assert run.execute_by_id("volumeup") is True
        assert CommandStats(stats_file).snapshot()["volumeup"]["count"] == 1

    def test_failure_does_not_bump(self, commands, mocker):
        matcher = self._matcher(commands, mocker)
        stats_file = stats_path_for(str(commands))
        if os.path.exists(stats_file):
            os.unlink(stats_file)
        error = mocker.patch("lib.voice_cmd.commands.subprocess.run")
        error.side_effect = subprocess.CalledProcessError(1, "cmd")
        assert matcher.execute_by_id("volumeup") is False
        assert CommandStats(stats_file).snapshot() == {}

    def test_sequence_bumps_composite_id(self, commands, mocker):
        matcher = self._matcher(commands, mocker)
        stats_file = stats_path_for(str(commands))
        if os.path.exists(stats_file):
            os.unlink(stats_file)
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        assert matcher.execute_by_id("combo") is True
        snap = CommandStats(stats_file).snapshot()
        assert snap["combo"]["count"] == 1         # засчитан составной id

    def test_sequence_bumps_each_step(self, commands, mocker):
        """Подшаг sequence тоже считается (combo → шаг volumeup)."""
        matcher = self._matcher(commands, mocker)
        stats_file = stats_path_for(str(commands))
        if os.path.exists(stats_file):
            os.unlink(stats_file)
        mocker.patch("lib.voice_cmd.commands.subprocess.run")
        assert matcher.execute_by_id("combo") is True
        snap = CommandStats(stats_file).snapshot()
        assert snap["volumeup"]["count"] == 1      # исполненный шаг засчитан

    def test_blocked_step_not_counted(self, commands, mocker):
        """Шаг, заблокированный requires, не попадает в статистику."""
        matcher = self._matcher(commands, mocker)
        stats_file = stats_path_for(str(commands))
        if os.path.exists(stats_file):
            os.unlink(stats_file)
        mocker.patch.object(
            matcher, "missing_requires", return_value=["media_session"])
        assert matcher.execute_by_id("volumeup") is False
        assert CommandStats(stats_file).snapshot() == {}

    def test_record_use_counts_outside_matcher(self, commands, mocker):
        """record_use пишет команду, запущенную мимо execute_by_id."""
        matcher = self._matcher(commands, mocker)
        stats_file = stats_path_for(str(commands))
        if os.path.exists(stats_file):
            os.unlink(stats_file)
        matcher.record_use("taskstart")
        assert CommandStats(stats_file).snapshot()["taskstart"]["count"] == 1
