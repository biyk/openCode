"""Тесты вкладки «Статистика» доски: HTML-отчёт и его место в /api/board."""

import json
import threading
import urllib.request

from lib.voice_cmd.knowledge_review_stats import _stamp, stats_html


def _commands(tmp_path):
    """Минимальный commands.json устройства (2 команды, без статистики)."""
    data = {"commands": {"volumeup": "c1", "dead": "c2"},
            "descriptions": {"volumeup": "увеличить громкость",
                             "dead": "никому не нужна"},
            "match": {}}
    path = tmp_path / "commands.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


class TestStatsHtml:
    def test_lists_commands_by_usage_desc(self, tmp_path):
        # На табе — наоборот CLI: частые сверху, «мёртвые» внизу.
        stats = {"volumeup": {"count": 3,
                              "last_seen": "2026-09-30T17:23:06"}}
        (tmp_path / "command_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False), encoding="utf-8")
        html = stats_html(_commands(tmp_path))
        assert "<table>" in html and "Статистика команд" in html
        assert html.index("volumeup") < html.index("dead")
        assert "2026-09-30 17:23" in html
        assert "ни разу не использовано: 1" in html

    def test_no_stats_file_is_ok(self, tmp_path):
        html = stats_html(_commands(tmp_path))
        assert "Всего команд: 2" in html
        assert "volumeup" in html

    def test_escapes_markup(self, tmp_path):
        data = {"commands": {"x": "c"}, "descriptions": {"x": "<script>"},
                "match": {}}
        path = tmp_path / "commands.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert "<script>" not in stats_html(str(path))

    def test_stamp_format(self):
        assert _stamp("2026-09-30T17:23:06") == "2026-09-30 17:23"
        assert _stamp("") == "—"


class TestBoardIncludesStats:
    def test_api_board_has_stats_tab_data(self, tmp_path):
        from lib.voice_cmd.knowledge import KnowledgeStore
        from lib.voice_cmd.knowledge_review_server import make_server

        httpd = make_server(KnowledgeStore(str(tmp_path / "k.json")),
                            _commands(tmp_path), {}, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{port}/api/board"
            with urllib.request.urlopen(url, timeout=5) as r:
                snap = json.loads(r.read().decode("utf-8"))
            assert "volumeup" in snap["stats"]
        finally:
            httpd.shutdown()
            httpd.server_close()
