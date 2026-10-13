"""Тесты вкладки «Сервисы» (`lib/monitor/ui.py`).

Вкладка вставляется в HTML доски, а не живёт отдельной страницей: проверяем,
что атрибуты совпадают с разметкой доски (`data-t` ↔ `id="t-…"`) и что JS не
содержит того, что ломало сборку строки (§4.5): backslash-продолжений и
шаблонных литералов.
"""
from lib.monitor.ui import TAB, TAB_ID, install
from lib.voice_cmd.knowledge_review_ui_log import page


def test_install_puts_tab_before_body_close():
    html = install("<html><body><div class=\"tabs\"></div></body></html>")
    assert html.count("</body>") == 1
    assert html.endswith(TAB + "\n</body></html>")


def test_install_on_real_board_page():
    html = install(page())
    assert html.count("</body>") == 1
    assert TAB in html
    # Скрипт вставляется после разметки `.tabs` — на момент выполнения
    # контейнер вкладок уже в DOM, иначе кнопка не нашлась бы.
    assert html.index(TAB) > html.index('class="tabs"')
    assert 'b.dataset.t="' + TAB_ID + '"' in html
    assert 'sec.id="t-' + TAB_ID + '"' in html


def test_tab_follows_board_tab_contract():
    """Доска переключает вкладки по соответствию `data-t` ↔ `id="t-…"`."""
    assert f'<button data-t="{TAB_ID}"' not in TAB  # кнопку делает скрипт
    assert 'b.dataset.t="' + TAB_ID + '"' in TAB
    assert 'sec.id="t-" + TAB_ID' in TAB or 'sec.id="t-services"' in TAB


def test_tab_pulls_monitor_endpoint_only_when_visible():
    assert "/api/monitor" in TAB
    assert 'classList.contains("on")' in TAB
    assert "setInterval(tick,2000)" in TAB


def test_tab_opens_directly_by_hash():
    """Прямая ссылка `#services` (её даёт open_board) выбирает вкладку."""
    assert 'location.hash==="#' + TAB_ID + '"' in TAB


def test_tab_shows_staleness_of_main_process():
    """Смысл панели — честный красный при зависшем main."""
    assert "stale" in TAB
    assert "heartbeat" in TAB
    assert "не отвечает" in TAB


def test_js_has_no_backslash_continuations_or_templates():
    """Backslash и `${}` внутри Python-строки ломали JS (§4.5)."""
    assert "\\" not in TAB
    assert "`" not in TAB
    assert "${" not in TAB


def test_states_cover_registry_vocabulary():
    for state in ("working", "idle", "disabled", "error", "never"):
        assert state in TAB
