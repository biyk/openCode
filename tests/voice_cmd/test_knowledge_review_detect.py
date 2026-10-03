"""Тесты двух фаз распознавания на доске и текстового следа (knowledge_review_detect).

След — то, что пользователь читает в попапе «логи»: в нём для КАЖДОГО уровня
либо число против порога, либо «пропущено» с причиной. Поэтому проверки — на
текст строк, а не только на результат.
"""

import json

import pytest

from lib.voice_cmd import knowledge_review_detect as kd

TITLES = ["Зарядка", "Пальцевая гимнастика"]


@pytest.fixture
def cfile(tmp_path):
    """commands.json с задачной командой (taskdone) и free-text (chat)."""
    data = {
        "commands": {"taskdone": "python -m lib.task_complete \"{{text}}\"",
                     "chat": "python -m lib.chat \"{{text}}\"",
                     "stop": "python -m lib.stop"},
        "match": {"taskdone": ["закончил задачу", "завершил"],
                  "chat": ["напиши"], "stop": ["стоп музыка"]},
        "decision": {"enabled": False},
    }
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _verdict(command="", conf=0.0, threshold=0.9, state="none"):
    return {"state": state, "command": command, "confidence": conf,
            "threshold": threshold}


def _stub(monkeypatch, laya=None, title=None, js=None, param=None):
    """Заглушки уровней (Лайя/задачи/LLM) — реальными ответами не рискуем."""
    monkeypatch.setattr(kd.lv, "llm_level", lambda review: "LLM race")
    monkeypatch.setattr(kd.lv, "laya_verdict",
                        lambda t, cf: laya or _verdict())
    monkeypatch.setattr(kd.lv, "laya_title", lambda t, names, cf: title or (
        _verdict(threshold=kd.kt.TITLE_THRESHOLD)))
    monkeypatch.setattr(kd.lv, "llm_json",
                        lambda t, ids, crit, review: (js, "LLM race"))
    monkeypatch.setattr(kd.lv, "llm_param",
                        lambda t, cmd, crit, review: param or ("", "LLM race"))


def _log(got):
    """След фразы с выровненными колонками: в тестах метки схлопнуты в один
    пробел (ширина поля — деталь оформления, а не смысл)."""
    return "\n".join(" ".join(line.split())
                     for line in got["trace"].splitlines())


class TestPhase1:
    def test_commands_hit_marks_others_skipped(self, monkeypatch, cfile):
        _stub(monkeypatch)
        got = kd.try_recognize("стоп музыка", cfile, {}, TITLES)
        assert got["via"] == "commands" and got["command"] == "stop"
        log = _log(got)
        assert 'commands.json: stop (1.00 >= 0.90) ключ "стоп музыка"' in log
        assert "Laya: пропущено, причина (фаза 1 завершена: commands.json)" \
            in log
        assert "LLM race: пропущено, причина (фаза 1 завершена: commands.json)" \
            in log

    def test_laya_hit_after_near_miss(self, monkeypatch, cfile):
        # тот же промах виден числом: рантайм бы здесь просто промолчал
        _stub(monkeypatch, laya=_verdict("taskdone", 0.9,
                                         kd.kt.MATCH_THRESHOLD, "hit"))
        got = kd.try_recognize("закончил пальцами гимнастику", cfile, {},
                               TITLES)
        lines = _log(got).splitlines()
        assert lines[0] == "фраза: закончил пальцами гимнастику"
        assert lines[1] == "фаза 1 определение команды"
        assert "taskdone (0." in lines[2] and "< 0.90" in lines[2]
        assert lines[2].endswith("не принято")
        assert "Laya: taskdone (0.90 >= 0.90)" in lines[3]
        assert lines[3].endswith("— фаза завершена")

    def test_llm_last(self, monkeypatch, cfile):
        _stub(monkeypatch, laya=_verdict("taskdone", 0.64, 0.9, "miss"),
              js={"kind": "command", "command": "stop", "event": ""})
        got = kd.try_recognize("завершении", cfile, {}, TITLES)
        assert got["via"] == "llm" and got["command"] == "stop"
        assert "Laya: taskdone (0.64 < 0.90)" in _log(got)
        assert "LLM race: stop" in _log(got)

    def test_nothing_recognized(self, monkeypatch, cfile):
        _stub(monkeypatch)
        got = kd.try_recognize("ы ы ы", cfile, {})
        assert got["via"] == "none" and got["kind"] == "none"
        assert "фаза 2 не нужна: команда не определена" in _log(got)
        assert "итог: команда —" in _log(got)

    def test_laya_absent_explained(self, monkeypatch, cfile):
        _stub(monkeypatch, laya=_verdict(state="off"))
        got = kd.try_recognize("ы ы ы", cfile, {})
        assert "Laya: пропущено, причина (decision выключен в commands.json)" \
            in _log(got)


class TestPhase2TaskParam:
    def test_words_after_key_win(self, monkeypatch, cfile):
        _stub(monkeypatch)
        got = kd.try_recognize("завершил Пальцевая гимнастика", cfile, {},
                               TITLES)
        assert got["command"] == "taskdone"
        assert got["event"] == "Пальцевая гимнастика"
        log = _log(got)
        assert "фаза 2 параметры команды taskdone" in log
        assert ('команда taskdone ключ "завершил" параметры '
                '"Пальцевая гимнастика"') in log
        assert "Laya: пропущено, причина (фаза 2 завершена: commands.json)" \
            in log

    def test_second_llm_question_when_laya_missed(self, monkeypatch, cfile):
        # фаза 1 закончилась Лайей → параметр всё равно спрашиваем у LLM
        _stub(monkeypatch, laya=_verdict("taskdone", 0.95, 0.9, "hit"),
              title=_verdict("Пальцевая гимнастика", 0.6,
                             kd.kt.TITLE_THRESHOLD, "miss"),
              param=("Пальцевая гимнастика", "LLM race"))
        got = kd.try_recognize("закончил пальцами гимнастику", cfile, {},
                               TITLES)
        assert got["event"] == "Пальцевая гимнастика"
        log = _log(got)
        assert "Laya: Пальцевая гимнастика (0.60 < 0.75)" in log
        assert "LLM race: Пальцевая гимнастика (1.00 >= 0.75)" in log
        assert log.rstrip().endswith('итог: команда taskdone ключ — '
                                     'параметры "Пальцевая гимнастика"')

    def test_laya_title_hit_stops_phase2(self, monkeypatch, cfile):
        _stub(monkeypatch, laya=_verdict("taskdone", 0.95, 0.9, "hit"),
              title=_verdict("Зарядка", 0.8, kd.kt.TITLE_THRESHOLD, "hit"))
        got = kd.try_recognize("закончил зарядку", cfile, {}, TITLES)
        assert got["event"] == "Зарядка"
        assert "LLM race: пропущено, причина (фаза 2 завершена: Laya)" \
            in _log(got)

    def test_weak_param_dropped(self, monkeypatch, cfile):
        _stub(monkeypatch, laya=_verdict("taskdone", 0.95, 0.9, "hit"),
              param=("Квантовая хроматография", "LLM race"))
        got = kd.try_recognize("закончил пальцами гимнастику", cfile, {},
                               TITLES)
        assert got["event"] == ""
        assert "не принято" in _log(got)

    def test_titles_read_once_when_not_given(self, monkeypatch, cfile):
        calls = []

        def titles():
            calls.append(1)
            return TITLES

        _stub(monkeypatch, laya=_verdict("taskdone", 0.95, 0.9, "hit"))
        monkeypatch.setattr(kd, "sheet_task_titles", titles)
        kd.try_recognize("закончил пальцами гимнастику", cfile, {})
        assert len(calls) == 1


class TestPhase2FreeText:
    def test_rest_is_param_without_threshold(self, monkeypatch, cfile):
        _stub(monkeypatch)
        got = kd.try_recognize("напиши привет мир", cfile, {}, TITLES)
        assert got["command"] == "chat" and got["event"] == "привет мир"
        log = _log(got)
        assert "commands.json: привет мир" in log
        assert log.rstrip().endswith('итог: команда chat ключ "напиши" '
                                     'параметры "привет мир"')
        assert "свободный текст {{text}}" in log

    def test_llm_param_without_answer(self, monkeypatch, cfile):
        _stub(monkeypatch, laya=_verdict("chat", 0.95, 0.9, "hit"))
        got = kd.try_recognize("напиши", cfile, {}, TITLES)
        assert got["event"] == ""
        assert "Laya: пропущено, причина (Лайя отвечает только на вопрос " \
            "«какая команда»)" in _log(got)
        assert "LLM race: нет ответа" in _log(got)
