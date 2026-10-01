# lib/voice_cmd/knowledge_review_stats.py
# TOOLTIP: Вкладка «Статистика» доски знаний: HTML-таблица частоты вызова команд
"""Вкладка «Статистика» доски знаний — частота запуска команд.

Считает по command_stats.build_report, но наоборот: по убыванию
использования — живые команды сверху, «мёртвые» (0 вызовов) внизу.
Данные read-only: доска только показывает, счётчик ведёт матчер
при исполнении команд. CLI-отчёт (`python -m lib.voice_cmd.command_stats`)
сохраняет свой порядок «мёртвые сверху» — там цель что удалять.
"""

import html

from lib.voice_cmd.command_stats import build_report


def _stamp(value: str) -> str:
    """'2026-09-30T17:28:46' → '2026-09-30 17:28' (без «T» и секунд)."""
    if not value:
        return "—"
    return value.replace("T", " ")[:16]


def stats_html(commands_file: str) -> str:
    """HTML-фрагмент вкладки: таблица вызовов (частые сверху) + итог."""
    rows = sorted(build_report(commands_file),
                  key=lambda r: (-r[0], r[2]))
    never = sum(1 for r in rows if r[0] == 0)
    head = ("<tr><th>вызовов</th><th>последний раз</th><th>id</th>"
            "<th>описание</th></tr>")
    body = "".join(
        f"<tr><td>{count}</td><td>{html.escape(_stamp(last))}</td>"
        f"<td>{html.escape(cmd_id)}</td>"
        f"<td class=note>{html.escape(desc)}</td></tr>"
        for count, last, cmd_id, desc in rows)
    return ("<h3>Статистика команд</h3><p class=note>Частота запуска по "
            "command_stats.json: сверху — самые используемые, внизу — ни "
            "разу не сработавшие (можно удалять). Счётчик растёт при "
            "каждом исполнении команды.</p>"
            f"<table>{head}{body or '<tr><td colspan=4>пусто</td></tr>'}"
            "</table>"
            f"<p class=note>Всего команд: {len(rows)}, ни разу не "
            f"использовано: {never}</p>")
