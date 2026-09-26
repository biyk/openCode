"""Тесты для манифеста скилла (SkillManifest)."""

from lib.skills.skills import SkillManifest, SkillStep


class TestSkillManifest:
    """Тесты для датакласса SkillManifest."""

    def test_skill_manifest_creation(self):
        """SkillManifest создаётся с правильными полями."""
        step = SkillStep(action="open_url", params={"url": "https://example.com"})
        manifest = SkillManifest(
            name="test_skill",
            description="Test skill",
            phrases=["фраза 1", "фраза 2"],
            params={"param1": {"type": "str", "required": True}},
            steps=[step],
        )
        assert manifest.name == "test_skill"
        assert manifest.description == "Test skill"
        assert manifest.phrases == ["фраза 1", "фраза 2"]
        assert len(manifest.steps) == 1
        assert manifest.steps[0].action == "open_url"
        assert manifest.steps[0].params == {"url": "https://example.com"}
