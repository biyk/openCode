"""Замеры CDP-транспорта: IPv6-ловушка localhost vs прямой 127.0.0.1.

Хром CDP слушает только IPv4; localhost сначала пробуется как ::1,
а отказ на Windows приходит примерно через 2 с. Отсюда платит и
HTTP (/json/*), и WebSocket (eval_js): метрики сравнивают оба пути.
"""

import json
import urllib.request

import pytest

from lib.browser import cdp_client

CDP_URLS = {
    "localhost": "http://localhost:{port}/json/version",
    "ipv4": "http://127.0.0.1:{port}/json/version",
}


def _open(url: str) -> None:
    with urllib.request.urlopen(url, timeout=5) as r:
        json.loads(r.read().decode("utf-8"))


@pytest.fixture(scope="module")
def cdp_up():
    """CDP должен отвечать по IPv4, иначе замерам не на чем виснуть."""
    try:
        _open(CDP_URLS["ipv4"].format(port=cdp_client.DEFAULT_PORT))
    except Exception:
        pytest.skip("браузер с CDP не запущен")
    return cdp_client.DEFAULT_PORT


class TestCdpSpeed:
    """Дешевизна прямого IPv4 против резолва localhost."""

    def test_version_localhost(self, bench, cdp_up):
        url = CDP_URLS["localhost"].format(port=cdp_up)
        bench.record("cdp.version_localhost", lambda: _open(url), runs=3)

    def test_version_ipv4(self, bench, cdp_up):
        url = CDP_URLS["ipv4"].format(port=cdp_up)
        bench.record("cdp.version_ipv4", lambda: _open(url), runs=3)

    def test_ws_connect(self, bench, cdp_up):
        """Открытие WebSocket к вкладке (каждый eval_js платит это)."""
        tabs = cdp_client._list_tabs(cdp_up)
        page = next((t for t in tabs if t.get("type") == "page"), None)
        if page is None:
            pytest.skip("нет ни одной вкладки page")

        def _open_ws():
            ws = cdp_client._ws_for(page)
            try:
                assert ws is not None
            finally:
                if ws is not None:
                    ws.close()

        bench.record("cdp.ws_connect", _open_ws, runs=3)

    def test_is_running_hot(self, bench, cdp_up):
        """Штатная проверка статуса browser (после фикса должна быть ~0)."""
        bench.record("cdp.is_running",
                     lambda: cdp_client.is_running(cdp_up), runs=3)
