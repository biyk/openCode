"""Тесты самой страницы доски: валидный JS и корректная разметка.

Ловят регресс «Uncaught SyntaxError: Unexpected string»: переносы строк
в Python-литерале PAGE (continuous backslash) не должны оставлять
обратные слэши внутри JS-строк и склеивать строковые литералы без «+».
"""

import re
import shutil
import subprocess

import pytest

from lib.voice_cmd.knowledge_review_ui import PAGE


def _script() -> str:
    m = re.search(r"<script>(.*?)</script>", PAGE, re.S)
    assert m, "на странице нет блока <script>"
    return m.group(1)


class TestPageSyntax:
    def test_no_backslash_inside_js_string_literals(self):
        for line in _script().splitlines():
            # перенос допустим между токенами, но не внутри '...' / "..."
            assert not re.search(r"['\"]\\$", line), f"битый перенос: {line}"

    def test_no_adjacent_string_literals(self):
        # JS не склеивает 'a'+'b' без «+» — это и есть «Unexpected string»;
        # в SOURCE-коде PAGE такой дефект виден как `'\` + перенос + `'`
        for chunk in re.findall(r"""['"]\\\n['"]""", PAGE):
            raise AssertionError(f"строки склеены без +: {chunk!r}")

    def test_page_renders_key_controls(self):
        for needle in ("id=recall", "id=scan", "распознать все",
                       "pollRec()", "pollScan()",
                       "S.commands.slice().sort()"):
            assert needle in PAGE

    def test_task_commands_show_sheet_tasks(self):
        # Под списком задач real_life_tasks (тянем их отдельно, по клику);
        # подсказка привязана к командам taskstart/taskdone (само-отчёт).
        for needle in ('T.map(', 'class=ti', 'class=tf', 'filterTasks(',
                       'cmd=="taskdone"', 'api("/api/tasks")',
                       'ensureTasks()'):
            assert needle in PAGE

    def test_no_kind_column(self):
        # Колонка «что делает» убрана: всё выражается колонкой «команда».
        assert "что делает" not in PAGE
        assert "kindSel" not in PAGE
        assert "KINDS" not in PAGE

    def test_cross_actions_per_bucket(self):
        # ✕ на «Подтверждено» — purge (commands.json + база знаний);
        # на «Лайе» — reset (в undefined), в «Не распознано» — forget.
        assert 'action:"purge"' in PAGE
        assert 'tr.dataset.bucket=="laya"?"reset":"forget"' in PAGE
        assert 'bucket=="confirmed"' in PAGE
        # в «Подтверждено» ✕ ставим и на locked-строках (т.к. чистим конфиг).
        assert "(e.locked||bucket==\"confirmed\")?\"\"" not in PAGE

    @pytest.mark.parametrize("wrapper", ["async function _main(){%s}",
                                         "%s"])
    def test_node_accepts_script(self, wrapper, tmp_path):
        node = shutil.which("node")
        if not node:
            pytest.skip("node недоступен")
        # верхний уровень ловит «await is only valid in async function»,
        # поэтому оборачиваем скрипт в async-функцию
        src = wrapper % _script()
        path = tmp_path / "board.js"
        path.write_text(src, encoding="utf-8")
        proc = subprocess.run([node, "--check", str(path)],
                              capture_output=True)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")

    def test_http_server_serves_valid_page(self, tmp_path):
        """Живой GET / отдаёт тот же валидный HTML (сервер не ломает JS)."""
        import json
        import threading
        import urllib.request

        from lib.voice_cmd.knowledge import KnowledgeStore
        from lib.voice_cmd.knowledge_review_server import make_server

        httpd = make_server(KnowledgeStore(str(tmp_path / "k.json")),
                            str(tmp_path / "commands.json"), {}, 0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/", timeout=5) as r:
                html = r.read().decode("utf-8")
            assert html == PAGE
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/ping", timeout=5) as r:
                assert json.loads(r.read().decode()) == {"ok": True}
        finally:
            httpd.shutdown()
            httpd.server_close()
