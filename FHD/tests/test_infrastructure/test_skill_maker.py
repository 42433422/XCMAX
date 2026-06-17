"""Tests for app.infrastructure.skills.skill_maker.skill_maker."""
from __future__ import annotations

import importlib
import os
import pytest
import tempfile

# skill-maker uses a hyphen, so we need importlib
_spec = importlib.util.spec_from_file_location(
    "skill_maker",
    os.path.join(os.path.dirname(__file__), "..", "..", "app", "infrastructure", "skills", "skill-maker", "skill_maker.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

get_base_dir = _mod.get_base_dir
get_skills_dir = _mod.get_skills_dir
list_existing_skills = _mod.list_existing_skills
create_skill_directory = _mod.create_skill_directory
create_skill_md = _mod.create_skill_md
create_skill = _mod.create_skill
validate_skill = _mod.validate_skill
get_skill_maker_skill = _mod.get_skill_maker_skill


class TestGetBaseDir:
    def test_returns_string(self):
        result = get_base_dir()
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetSkillsDir:
    def test_returns_path_with_skills(self):
        result = get_skills_dir()
        assert ".trae" in result
        assert "skills" in result


class TestListExistingSkills:
    def test_nonexistent_dir_returns_empty(self, monkeypatch, tmp_path):
        # Override get_skills_dir by monkeypatching the module
        nonexistent = str(tmp_path / "nonexistent_skills")
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: nonexistent)
        result = list_existing_skills()
        assert result == []

    def test_lists_skill_directories(self, monkeypatch, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my-skill").mkdir()
        (skills_dir / "my-skill" / "SKILL.md").write_text("# My Skill")

        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(skills_dir))
        result = list_existing_skills()
        assert len(result) == 1
        assert result[0]["name"] == "my-skill"
        assert result[0]["has_skill_md"] is True

    def test_skill_without_md(self, monkeypatch, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "bare-skill").mkdir()

        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(skills_dir))
        result = list_existing_skills()
        assert len(result) == 1
        assert result[0]["has_skill_md"] is False


class TestCreateSkillDirectory:
    def test_creates_directory(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill_directory("new-skill")
        assert result["success"] is True
        assert (tmp_path / "new-skill").is_dir()

    def test_existing_directory_returns_failure(self, monkeypatch, tmp_path):
        (tmp_path / "existing-skill").mkdir()
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill_directory("existing-skill")
        assert result["success"] is False


class TestCreateSkillMd:
    def test_creates_md_file(self, monkeypatch, tmp_path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill_md("test-skill", "A test skill")
        assert result["success"] is True
        assert (skill_dir / "SKILL.md").exists()

    def test_custom_content(self, monkeypatch, tmp_path):
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill_md("test-skill", "Desc", content="# Custom")
        assert result["success"] is True
        content = (skill_dir / "SKILL.md").read_text()
        assert "Custom" in content

    def test_creates_dir_if_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill_md("new-skill", "Desc")
        assert result["success"] is True


class TestCreateSkill:
    def test_full_skill_creation(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill(
            "my-skill",
            "A test skill",
            create_init=True,
            create_impl=True,
        )
        assert result["success"] is True
        assert len(result["files_created"]) == 3  # SKILL.md + __init__.py + impl.py

    def test_skill_without_init_or_impl(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill("simple-skill", "Simple")
        assert result["success"] is True
        assert len(result["files_created"]) == 1  # SKILL.md only

    def test_duplicate_skill_returns_failure(self, monkeypatch, tmp_path):
        (tmp_path / "dup-skill").mkdir()
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = create_skill("dup-skill", "Duplicate")
        assert result["success"] is False


class TestValidateSkill:
    def test_nonexistent_skill(self, monkeypatch, tmp_path):
        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = validate_skill("missing")
        assert result["valid"] is False

    def test_valid_skill(self, monkeypatch, tmp_path):
        skill_dir = tmp_path / "good-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text('---\nname: "good-skill"\ndescription: "Good"\n---\n# Good')
        (skill_dir / "__init__.py").write_text("")

        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = validate_skill("good-skill")
        assert result["valid"] is True
        assert len(result["issues"]) == 0

    def test_skill_missing_md(self, monkeypatch, tmp_path):
        skill_dir = tmp_path / "no-md-skill"
        skill_dir.mkdir()

        monkeypatch.setattr(_mod, "get_skills_dir", lambda: str(tmp_path))
        result = validate_skill("no-md-skill")
        assert result["valid"] is False
        assert "Missing SKILL.md file" in result["issues"]


class TestGetSkillMakerSkill:
    def test_returns_dict(self):
        result = get_skill_maker_skill()
        assert result["name"] == "skill-maker"
        assert "functions" in result
        assert "list_existing_skills" in result["functions"]
        assert "create_skill" in result["functions"]
        assert "validate_skill" in result["functions"]
