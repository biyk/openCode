# TOOLTIP: Тесты учёта проглоченных ошибок (lib/core/errors.py)
"""Тесты swallowed(): возврат default, лог, подсказка про reauth."""

import logging

from lib.core.errors import AUTH_HINT, INFO, is_auth_error, swallowed


class RefreshError(Exception):
    """Двойник google RefreshError — угадывается по имени класса."""


class _FakeResp:
    def __init__(self, status):
        self.status = status


class _FakeHttpError(Exception):
    """Двойник googleapiclient HttpError (атрибут resp.status)."""

    def __init__(self, status):
        super().__init__("http error")
        self.resp = _FakeResp(status)


def test_swallowed_returns_default():
    exc = ValueError("boom")
    assert swallowed("x.y", exc, False) is False
    assert swallowed("x.y", exc, "") == ""
    assert swallowed("x.y", exc) is None


def test_swallowed_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="voice.errors"):
        swallowed("x.y", ValueError("boom"), None)
    assert "[Swallowed] x.y: ValueError: boom" in caplog.text


def test_auth_hint_for_refresh_error(caplog):
    with caplog.at_level(logging.WARNING, logger="voice.errors"):
        swallowed("tasks.refresh_token", RefreshError("token_expired"), "")
    assert AUTH_HINT in caplog.text


def test_auth_hint_for_http_401(caplog):
    with caplog.at_level(logging.WARNING, logger="voice.errors"):
        swallowed("gcal.delete_event", _FakeHttpError(401), False)
    assert AUTH_HINT in caplog.text


def test_no_auth_hint_for_plain_error(caplog):
    with caplog.at_level(logging.WARNING, logger="voice.errors"):
        swallowed("gcal.delete_event", OSError("нет сети"), False)
    assert AUTH_HINT not in caplog.text


def test_info_level_for_probes(caplog):
    with caplog.at_level(logging.INFO, logger="voice.errors"):
        swallowed("gcal.get_event", _FakeHttpError(404), None, level=INFO)
    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.INFO]


def test_is_auth_error_negative():
    assert is_auth_error(ValueError("x")) is False
    assert is_auth_error(_FakeHttpError(500)) is False
