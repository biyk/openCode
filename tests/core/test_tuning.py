"""Тесты центра настройки lib.core.tuning: пороги зафиксированы и прокинуты.

Гаранты против тихого расползания магических чисел: единая ручка в tuning,
все модули берут значения оттуда, а decision-порог достаточно высок, чтобы
ложная уверенность (~0.6) не запускала команду.
"""

import json
import os

from lib.core import tuning
from lib.core.laya_batch import BATCH_OPTS, MAX_OPTS
from lib.core.laya_decision import LayaDecision
from lib.core.orchestrator_event_match import EVENT_ACTION_THRESHOLD
from lib.google.shopping_dedup import DEFAULT_THRESHOLD as SHOP_DEFAULT
from lib.taskflow.tasks_dedup import BATCH_THRESHOLD, DUP_THRESHOLD
from lib.task_start import TITLE_THRESHOLD, TOKEN_RATIO, TOKEN_ROOT_PREFIX

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class TestThresholdsAreStrict:
    def test_decision_gate_rejects_coin_flip(self):
        """Порог команд не ниже 0.9: уверенность ~0.6 — «почти угадала»."""
        assert tuning.DECISION_THRESHOLD >= 0.9

    def test_event_and_title_thresholds_present(self):
        assert 0.0 < tuning.EVENT_ACTION_THRESHOLD <= 1.0
        assert 0.0 < tuning.TITLE_THRESHOLD <= 1.0


class TestModulesReadFromTuning:
    def test_laya_batch_limit(self):
        assert MAX_OPTS == tuning.LAYA_MAX_OPTS
        assert BATCH_OPTS == tuning.LAYA_MAX_OPTS - 1

    def test_tasks_dedup_binds(self):
        assert DUP_THRESHOLD == tuning.DEDUP_THRESHOLD
        assert BATCH_THRESHOLD == tuning.DEDUP_BATCH_THRESHOLD

    def test_shopping_binds(self):
        assert SHOP_DEFAULT == tuning.SHOPPING_DEDUP_THRESHOLD

    def test_task_start_binds(self):
        assert TITLE_THRESHOLD == tuning.TITLE_THRESHOLD
        assert TOKEN_ROOT_PREFIX == tuning.TOKEN_ROOT_PREFIX
        assert TOKEN_RATIO == tuning.TOKEN_RATIO

    def test_event_action_binds(self):
        assert EVENT_ACTION_THRESHOLD == tuning.EVENT_ACTION_THRESHOLD


class TestLayaDecisionDefault:
    def test_default_threshold_comes_from_tuning(self):
        """Без decision.threshold в конфиге — берётся DECISION_THRESHOLD."""
        client = LayaDecision({"url": "http://x"})
        assert client._threshold == tuning.DECISION_THRESHOLD

    def test_config_override_still_wins(self):
        """Пер-девайсный оверрайд в commands.json имеет приоритет."""
        client = LayaDecision({"url": "http://x", "threshold": 0.42})
        assert client._threshold == 0.42


class TestDeviceConfigRaised:
    def test_live_device_threshold_not_loose(self):
        """FLTP-девайс: decision.threshold ≥ 0.9 (иначе ложные wakefix)."""
        path = os.path.join(REPO, "targets", "FLTP-5i3-16512",
                            "commands.json")
        if not os.path.isfile(path):
            return
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["decision"]["threshold"] >= 0.9


class TestDevelopmentDoneIsAnnounced:
    """Окончание разработки обязательно озвучивается (явное требование).

    Хук post-commit — то место, где работа считается завершённой; тест ловит
    тихую потерю озвучки (скрипт/константа/вызов из хука).
    """

    def test_done_text_is_not_empty(self):
        assert tuning.TASK_DONE_TEXT.strip()

    def test_announce_script_uses_the_same_text(self):
        from scripts.announce_done import done_text
        assert done_text() == tuning.TASK_DONE_TEXT

    def test_post_commit_hook_calls_announce(self):
        hook = os.path.join(REPO, ".git", "hooks", "post-commit")
        if not os.path.isfile(hook):
            return
        with open(hook, encoding="utf-8", errors="replace") as fh:
            assert "announce_done.py" in fh.read()
