"""Регресс: корень проекта для auto_launch Laya не зависит от глубины файла."""

import os

from lib.core.laya_decision import _projects_root


def test_projects_root_is_repo_root():
    """_projects_root() указывает на каталог с lib/, а не на сам lib/.

    Пути `auto_launch` в commands.json (`laya-lab/bin/laya.exe`, модель)
    относительные от корня проекта: съехавший на уровень корень даёт
    «exe/модель не найдены» и отключение decision-слоя.
    """
    root = _projects_root()
    assert os.path.basename(root) != "lib"
    assert os.path.isdir(os.path.join(root, "lib"))
    assert os.path.isfile(os.path.join(root, "VERSION"))
