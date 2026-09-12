"""Тесты для загрузки и поиска скиллов (SkillRegistry)."""

import json

from lib.skills import SkillRegistry


class TestSkillRegistryLoading:
    """Тесты загрузки и индексации скиллов."""

    def _make_registry(self, tmp_path, skills=None):
        """Создаёт реестр с временной папкой и опциональными скиллами."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        if skills:
            for name, data in skills.items():
                (skills_dir / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
        return SkillRegistry(skills_dir=str(skills_dir)), skills_dir

    def test_load_empty_dir(self, tmp_path):
        """load() на пустой папке не падает и не загружает скиллов."""
        registry, _ = self._make_registry(tmp_path)
        registry.load()
        assert registry.list_skills() == []

    def test_load_missing_dir(self, tmp_path):
        """load() на несуществующей папке не падает."""
        registry = SkillRegistry(skills_dir=str(tmp_path / "nonexistent"))
        registry.load()
        assert registry.list_skills() == []

    def test_load_single_skill(self, tmp_path):
        """Загрузка одного валидного скилла."""
        skill_data = {
            "name": "test_skill",
            "description": "Test",
            "phrases": ["открой тест", "запусти тест"],
            "params": {},
            "steps": [{"action": "open_url", "params": {"url": "https://example.com"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"test_skill": skill_data})
        registry.load()
        assert registry.list_skills() == ["test_skill"]
        skill = registry.get_skill("test_skill")
        assert skill is not None
        assert skill.name == "test_skill"
        assert skill.phrases == ["открой тест", "запусти тест"]
        assert len(skill.steps) == 1
        assert skill.steps[0].action == "open_url"

    def test_load_invalid_json_skipped(self, tmp_path):
        """Невалидный JSON пропускается с логом ошибки."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "bad.json").write_text("{invalid}")
        registry = SkillRegistry(skills_dir=str(skills_dir))
        registry.load()
        assert registry.list_skills() == []

    def test_match_exact_phrase(self, tmp_path):
        """match() находит скилл по точной фразе (case-insensitive)."""
        skill_data = {
            "name": "youtube",
            "description": "Open YouTube",
            "phrases": ["открой ютуб", "включи ютуб"],
            "params": {},
            "steps": [{"action": "open_url", "params": {"url": "https://youtube.com"}}],
        }
        registry, _ = self._make_registry(tmp_path, {"youtube": skill_data})
        assert registry.match("открой ютуб") == "youtube"
        assert registry.match("ОТКРОЙ ЮТУБ") == "youtube"
        assert registry.match("  открой ютуб  ") == "youtube"

    def test_match_no_match(self, tmp_path):
        """match() возвращает None для неизвестной фразы."""
        skill_data = {
            "name": "youtube",
            "phrases": ["открой ютуб"],
            "params": {},
            "steps": [],
        }
        registry, _ = self._make_registry(tmp_path, {"youtube": skill_data})
        assert registry.match("открой гугл") is None
        assert registry.match("") is None

    def test_reload_clears_cache(self, tmp_path):
        """reload() перечитывает файлы."""
        import json

        registry, skills_dir = self._make_registry(tmp_path)
        registry.load()
        assert "new_skill" not in registry.list_skills()
        # Add new skill file after initial load
        (tmp_path / "skills" / "new_skill.json").write_text(
            json.dumps({"name": "new_skill", "phrases": ["новая"], "params": {}, "steps": []})
        )
        registry.reload()
        assert "new_skill" in registry.list_skills()
