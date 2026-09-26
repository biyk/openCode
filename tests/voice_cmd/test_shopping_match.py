"""Тесты команд списка покупок на живом конфиге устройства.

Уровень 1 (правило «трёх строк», §10 AGENTS.md) проверяется по реальному
targets/FLTP-5i3-16512/commands.json: шаблоны «купил» и «купить» похожи
(≈0.91), и тест гарантирует, что они не перетягивают друг друга, а
{{text}} собирает название товара.
"""

import json
from pathlib import Path

import pytest

from lib.voice_cmd.commands import CommandMatcher

CONFIG = (Path(__file__).resolve().parents[2]
          / "targets" / "FLTP-5i3-16512" / "commands.json")

pytestmark = pytest.mark.skipif(
    not CONFIG.exists(), reason="конфиг устройства не найден")


@pytest.fixture
def matcher():
    return CommandMatcher(str(CONFIG))


@pytest.fixture
def config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_add_and_bought_do_not_steal_each_other(matcher):
    """«нужно купить X» → shop-add, «купил X» → shop-bought, товар — настройка."""
    assert matcher.find_command(["алиса нужно купить молоко"]) == (
        "shop-add", ["молоко"], False)
    assert matcher.find_command(["алиса купил молоко"]) == (
        "shop-bought", ["молоко"], False)
    assert matcher.find_command(["алиса я купил хлеб"]) == (
        "shop-bought", ["хлеб"], False)


def test_command_on_line_after_key(matcher):
    """Ключ в одной строке, команда в следующей — три строки потока (§10)."""
    assert matcher.find_command(["алиса", "надо купить сыр"]) == (
        "shop-add", ["сыр"], False)


def test_templates_pass_product_to_cli(matcher):
    """{{text}} уходит аргументом python -m lib.shopping (add|bought)."""
    assert matcher.needs_text("shop-add") and matcher.needs_text("shop-bought")
    add = matcher.get_command("shop-add", ("молоко",))
    buy = matcher.get_command("shop-bought", ("хлеб батон",))
    assert add.endswith('lib.shopping add "молоко"')
    assert buy.endswith('lib.shopping bought "хлеб батон"')


def test_shopping_section_points_to_the_table(config):
    """Секция shopping: таблица списка покупок, дедуп выключен (на будущее)."""
    shopping = config["shopping"]
    assert shopping["spreadsheet_id"] == \
        "1GPiQPzUWRZ0G23OlSCTIVt266TZh_AcGM1B0F7W71jo"
    assert shopping["sheet_name"] == "Лист1" and shopping["sheet_id"] == 0
    assert shopping["dedup"]["enabled"] is False
    assert shopping["dedup"]["fuzzy"] is False


def test_laya_criteria_describe_both_commands(config):
    """Decision-слой обязан различать «купить» и «купил» (шаг 2, §4.2)."""
    criteria = config["decision"]["criteria"]
    assert "shop-add" in criteria and "shop-bought" in criteria
    assert "список покупок" in criteria["shop-add"]
    assert "НЕ просьба что-то купить" in criteria["shop-bought"]
