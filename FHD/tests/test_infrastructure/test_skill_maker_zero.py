"""Tests for app.infrastructure.skills.skill_maker.skill_maker."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# skill-maker has a hyphen, so we use importlib to load it
_spec = importlib.util.spec_from_file_location(
    "skill_maker",
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "app",
        "infrastructure",
        "skills",
        "skill-maker",
        "skill_maker.py",
    ),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

create_skill = _mod.create_skill
create_skill_directory = _mod.create_skill_directory
create_skill_md = _mod.create_skill_md
get_skill_maker_skill = _mod.get_skill_maker_skill
list_existing_skills = _mod.list_existing_skills
validate_skill = _mod.validate_skill


class TestListExistingSkills:
    """Tests for list_existing_skills."""

    def test_returns_empty_when_dir_not_exists(self, tmp_path: Path) -> None:
        with patch.object(_mod, "get_skills_dir", return_value=str(tmp_path / "nonexistent")):
            result = list_existing_skills()
            assert result == []

    def test_lists_skill_directories(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my-skill").mkdir()
        (skills_dir / "my-skill" / "SKILL.md").write_text("---\nname: my-skill\n---")
        (skills_dir / "another").mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = list_existing_skills()
            names = [s["name"] for s in result]
            assert "my-skill" in names
            assert "another" in names
            my_skill = next(s for s in result if s["name"] == "my-skill")
            assert my_skill["has_skill_md"] is True

    def test_skill_without_skill_md(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "bare-skill").mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = list_existing_skills()
            bare = next(s for s in result if s["name"] == "bare-skill")
            assert bare["has_skill_md"] is False


class TestCreateSkillDirectory:
    """Tests for create_skill_directory."""

    def test_creates_new_directory(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill_directory("test-skill")
            assert result["success"] is True
            assert os.path.isdir(os.path.join(str(skills_dir), "test-skill"))

    def test_fails_if_already_exists(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "existing").mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill_directory("existing")
            assert result["success"] is False
            assert "already exists" in result["message"]


class TestCreateSkillMd:
    """Tests for create_skill_md."""

    def test_creates_default_content(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "my-skill").mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill_md("my-skill", "A test skill")
            assert result["success"] is True
            md_path = os.path.join(str(skills_dir), "my-skill", "SKILL.md")
            assert os.path.isfile(md_path)
            content = open(md_path).read()
            assert "my-skill" in content
            assert "A test skill" in content

    def test_creates_with_custom_content(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "custom-skill").mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            custom = "---\nname: custom\n---\nCustom content"
            result = create_skill_md("custom-skill", "desc", content=custom)
            assert result["success"] is True
            md_path = os.path.join(str(skills_dir), "custom-skill", "SKILL.md")
            assert "Custom content" in open(md_path).read()

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill_md("new-skill", "desc")
            assert result["success"] is True
            assert os.path.isdir(os.path.join(str(skills_dir), "new-skill"))


class TestCreateSkill:
    """Tests for create_skill."""

    def test_full_skill_creation(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill(
                "full-skill",
                "Full skill desc",
                create_init=True,
                create_impl=True,
            )
            assert result["success"] is True
            assert len(result["files_created"]) == 3
            skill_path = os.path.join(str(skills_dir), "full-skill")
            assert os.path.isfile(os.path.join(skill_path, "SKILL.md"))
            assert os.path.isfile(os.path.join(skill_path, "__init__.py"))
            assert os.path.isfile(os.path.join(skill_path, "full_skill.py"))

    def test_skill_creation_without_init_impl(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill("basic-skill", "Basic desc")
            assert result["success"] is True
            assert len(result["files_created"]) == 1

    def test_skill_creation_fails_if_exists(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "dup-skill").mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill("dup-skill", "Duplicate")
            assert result["success"] is False

    def test_skill_with_custom_impl_content(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = create_skill(
                "custom-impl",
                "desc",
                create_impl=True,
                impl_content="def custom_fn(): pass\n",
            )
            assert result["success"] is True
            impl_path = os.path.join(str(skills_dir), "custom-impl", "custom_impl.py")
            assert "custom_fn" in open(impl_path).read()


class TestValidateSkill:
    """Tests for validate_skill."""

    def test_nonexistent_skill(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = validate_skill("nonexistent")
            assert result["valid"] is False
            assert "does not exist" in result["message"]

    def test_valid_skill_with_all_files(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_path = skills_dir / "valid-skill"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text(
            '---\nname: "valid-skill"\ndescription: "A skill"\n---\n'
        )
        (skill_path / "__init__.py").write_text("")
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = validate_skill("valid-skill")
            assert result["valid"] is True
            assert len(result["issues"]) == 0

    def test_skill_missing_skill_md(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_path = skills_dir / "no-md"
        skill_path.mkdir()
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = validate_skill("no-md")
            assert result["valid"] is False
            assert any("SKILL.md" in i for i in result["issues"])

    def test_skill_missing_init(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_path = skills_dir / "no-init"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text('---\nname: "no-init"\ndescription: "desc"\n---\n')
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = validate_skill("no-init")
            assert any("__init__" in w for w in result["warnings"])

    def test_skill_invalid_frontmatter(self, tmp_path: Path) -> None:
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        skill_path = skills_dir / "bad-frontmatter"
        skill_path.mkdir()
        (skill_path / "SKILL.md").write_text("# Just a heading\nNo frontmatter here")
        with patch.object(_mod, "get_skills_dir", return_value=str(skills_dir)):
            result = validate_skill("bad-frontmatter")
            assert any("name" in w for w in result["warnings"])
            assert any("description" in w for w in result["warnings"])


class TestGetSkillMakerSkill:
    """Tests for get_skill_maker_skill."""

    def test_returns_skill_dict(self) -> None:
        result = get_skill_maker_skill()
        assert result["name"] == "skill-maker"
        assert "list_existing_skills" in result["functions"]
        assert "create_skill" in result["functions"]
        assert "validate_skill" in result["functions"]
