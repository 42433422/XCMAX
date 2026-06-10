"""Test NLCodeSkillFactory: NL → CodeSkill with sandbox verification + repair."""

from __future__ import annotations

import json

import pytest

from vibe_coding.runtime import CodeSkillRuntime, JsonCodeSkillStore
from vibe_coding import MockLLM
from vibe_coding.code_factory import NLCodeSkillFactory, VibeCodingError


def _spec(skill_id: str, fn: str = "demo") -> str:
    return json.dumps(
        {
            "skill_id": skill_id,
            "name": skill_id,
            "domain": "",
            "function_name": fn,
            "purpose": "demo",
            "signature": {"params": ["value"], "return_type": "dict", "required_params": ["value"]},
            "dependencies": [],
            "test_cases": [
                {
                    "case_id": "happy",
                    "input_data": {"value": "hi"},
                    "expected_output": {"out": "hi"},
                }
            ],
            "quality_gate": {"required_keys": ["out"]},
            "domain_keywords": [],
        }
    )


def _good_code(fn: str = "demo") -> str:
    return json.dumps(
        {
            "source_code": (
                f"def {fn}(value):\n"
                "    \"\"\"Echo string input as {'out': value}.\"\"\"\n"
                "    if not isinstance(value, str):\n"
                "        return {'out': '', 'error': 'not_str'}\n"
                "    return {'out': value}\n"
            )
        }
    )


def _bad_code(fn: str = "demo") -> str:
    """Triggers KeyError because subscript access on missing key."""
    return json.dumps(
        {
            "source_code": (
                f"def {fn}(value):\n"
                "    \"\"\"Broken implementation used to exercise repair.\"\"\"\n"
                "    return {'out': value['nope']}\n"
            )
        }
    )


def test_brief_first_happy_path(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    llm = MockLLM([_spec("s1"), _good_code()])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("any brief")
    assert skill.skill_id == "s1"
    assert skill.active_version == 1
    assert "def demo(value)" in skill.get_active_version().source_code
    # Persisted
    assert store.has_code_skill("s1")


def test_direct_mode_uses_one_call(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    payload = json.loads(_spec("s2"))
    payload["source_code"] = json.loads(_good_code())["source_code"]
    llm = MockLLM([json.dumps(payload)])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("brief", mode="direct")
    assert skill.skill_id == "s2"
    assert len(llm.calls) == 1


def test_factory_retries_parse_failure_with_json_only_prompt(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    payload = json.loads(_spec("s-json-retry"))
    payload["source_code"] = json.loads(_good_code())["source_code"]
    llm = MockLLM(["not json at all", json.dumps(payload)])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("brief", mode="direct")
    assert skill.skill_id == "s-json-retry"
    assert len(llm.calls) == 2
    assert "无法解析" in llm.calls[1].user


def test_brief_first_normalizes_missing_optional_schema_fields(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    spec = {
        "skill_id": "schema-lite",
        "name": "schema lite",
        "test_cases": [{"input_data": {"value": "ok"}, "expected_output": {"out": "ok"}}],
    }
    llm = MockLLM([json.dumps(spec), _good_code("schema_lite")])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("brief")
    version = skill.get_active_version()
    assert version.function_name == "schema_lite"
    assert version.signature.return_type == "dict"


def test_repair_loop_recovers_from_bad_code(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    # spec, then bad code (sandbox-fail), then a repair that returns good code
    llm = MockLLM([_spec("s3"), _bad_code(), _good_code()])
    factory = NLCodeSkillFactory(llm, store, max_repair_rounds=2)
    skill = factory.generate("brief")
    assert skill.skill_id == "s3"
    # 3 LLM calls: spec, code, repair
    assert len(llm.calls) == 3


def test_repair_exhausts_and_raises(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    # Always bad: spec + code(bad) + repair(bad) + repair(bad)
    llm = MockLLM([_spec("s4"), _bad_code(), _bad_code(), _bad_code()])
    factory = NLCodeSkillFactory(llm, store, max_repair_rounds=2)
    with pytest.raises(VibeCodingError):
        factory.generate("brief")


def test_validation_rejects_forbidden_import(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    spec = json.loads(_spec("s5"))
    bad_code = {
        "source_code": (
            "import os\n"
            "def demo(value):\n"
            "    \"\"\"Return value through the out key.\"\"\"\n"
            "    return {'out': value}\n"
        )
    }
    # spec, bad import, repair good
    llm = MockLLM([json.dumps(spec), json.dumps(bad_code), _good_code()])
    factory = NLCodeSkillFactory(llm, store, max_repair_rounds=2)
    skill = factory.generate("brief")
    assert "import os" not in skill.get_active_version().source_code


def test_skill_id_override_takes_effect(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    llm = MockLLM([_spec("auto-id"), _good_code()])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("brief", skill_id="user_chose_this_id")
    assert skill.skill_id == "user-chose-this-id"


def _make_project_dir(root):
    """Create a realistic project directory for analysis tests."""
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "node-vue-app",
                "version": "1.2.3",
                "description": "A Vue 3 demo app",
                "scripts": {"dev": "vite --host 0.0.0.0", "build": "vite build", "test": "vitest"},
                "dependencies": {"vue": "^3.4.0", "pinia": "^2.1.0"},
                "devDependencies": {"vite": "^5.0.0", "typescript": "^5.0.0", "vitest": "^1.0.0"},
            }
        ),
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "App.vue").write_text("<template />\n", encoding="utf-8")
    (root / "src" / "main.ts").write_text("import { createApp } from 'vue'\n", encoding="utf-8")
    (root / "vite.config.ts").write_text("export default {}\n", encoding="utf-8")
    (root / "tsconfig.json").write_text("{}\n", encoding="utf-8")
    (root / "README.md").write_text("# Old README\nOld content.\n", encoding="utf-8")


def test_project_root_analysis_is_injected_for_readme_skills(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    _make_project_dir(project)

    store = JsonCodeSkillStore(tmp_path / "store.json")
    llm = MockLLM([_spec("readme-skill"), _good_code()])
    factory = NLCodeSkillFactory(llm, store)
    factory.generate("生成这个项目的 README", project_root=project)

    first_prompt = llm.calls[0].user
    assert "项目结构分析" in first_prompt
    assert "package.json" in first_prompt
    assert "Node.js" in first_prompt
    assert "Vue" in first_prompt
    assert "Vite" in first_prompt
    # README brief triggers the "怎么做" doc-generator instructions.
    assert "怎么做" in first_prompt
    assert "project_analysis" in first_prompt


def test_project_root_analysis_includes_rich_fields(tmp_path):
    """analyze_project returns entry_points, config_files, readme_snippet, git_info."""
    from vibe_coding.code_factory import analyze_project

    project = tmp_path / "proj"
    project.mkdir()
    _make_project_dir(project)

    analysis = analyze_project(project)

    assert analysis.root_name == "proj"
    assert "vue" in analysis.languages or "typescript" in analysis.languages
    assert "Vue" in analysis.tech_stack
    assert "src/main.ts" in analysis.entry_points
    assert "vite.config.ts" in analysis.config_files
    assert "tsconfig.json" in analysis.config_files
    assert "Old README" in analysis.readme_snippet
    # git_info may be empty if git is not configured in the tmp dir – that is OK.
    assert isinstance(analysis.git_info, dict)


def test_doc_generation_brief_injects_how_to_do_instructions(tmp_path):
    """When brief is doc-type and project_root is given, the enriched prompt
    contains 'how-to-do' steps (怎么做) and references project_analysis parameter."""
    project = tmp_path / "proj2"
    project.mkdir()
    _make_project_dir(project)

    store = JsonCodeSkillStore(tmp_path / "store.json")
    llm = MockLLM([_spec("doc-skill"), _good_code()])
    factory = NLCodeSkillFactory(llm, store)
    factory.generate("生成项目文档说明", project_root=project)

    first_prompt = llm.calls[0].user
    assert "怎么做" in first_prompt
    assert "project_analysis" in first_prompt
    assert "manifests" in first_prompt
    assert "tech_stack" in first_prompt
    assert "entry_points" in first_prompt


def test_non_doc_brief_does_not_inject_how_to_do(tmp_path):
    """A non-documentation brief with project_root must NOT inject the '怎么做' block."""
    project = tmp_path / "proj3"
    project.mkdir()
    _make_project_dir(project)

    store = JsonCodeSkillStore(tmp_path / "store.json")
    llm = MockLLM([_spec("other-skill"), _good_code()])
    factory = NLCodeSkillFactory(llm, store)
    factory.generate("计算两个数之和", project_root=project)

    first_prompt = llm.calls[0].user
    # Project analysis block is still injected…
    assert "项目结构分析" in first_prompt
    # …but the doc-specific 怎么做 steps should not appear.
    assert "怎么做（文档生成器强制步骤）" not in first_prompt


def test_to_prompt_block_includes_new_fields(tmp_path):
    """ProjectAnalysis.to_prompt_block must include entry_points, config_files, readme_snippet."""
    from vibe_coding.code_factory import ProjectAnalysis

    analysis = ProjectAnalysis(
        root_name="test-proj",
        manifests={"package.json": {"name": "test", "scripts": {}, "notable_dependencies": {}}},
        top_level=["src/", "package.json"],
        languages={"typescript": 5},
        tech_stack=["Node.js", "TypeScript"],
        entry_points=["src/main.ts"],
        config_files=["tsconfig.json", "vite.config.ts"],
        readme_snippet="# My Project",
        git_info={"recent_commits": ["abc123 initial commit"]},
    )
    block = analysis.to_prompt_block()

    assert "entry_points" in block
    assert "src/main.ts" in block
    assert "config_files" in block
    assert "tsconfig.json" in block
    assert "readme_snippet" in block
    assert "My Project" in block
    assert "git_info" in block
    assert "initial commit" in block


def test_runtime_self_heals_after_persisted(tmp_path):
    """Generated skill is immediately runnable; runtime auto-patches a KeyError."""
    store = JsonCodeSkillStore(tmp_path / "store.json")
    spec = {
        "skill_id": "extract",
        "name": "extract",
        "domain": "",
        "function_name": "extract",
        "purpose": "extract name",
        "signature": {"params": ["user"], "return_type": "dict", "required_params": ["user"]},
        "dependencies": [],
        "test_cases": [
            {
                "case_id": "happy",
                "input_data": {"user": {"name": "ada"}},
                "expected_output": {"name": "ada"},
            }
        ],
        "quality_gate": {"required_keys": ["name"]},
        "domain_keywords": [],
    }
    code = {"source_code": "def extract(user):\n    \"\"\"Extract name from a user dict.\"\"\"\n    return {'name': user['name']}\n"}
    llm = MockLLM([json.dumps(spec), json.dumps(code)])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("extract name from user")
    assert skill.active_version == 1

    runtime = CodeSkillRuntime(store)
    run = runtime.run(skill.skill_id, {"user": {}})
    assert run.stage == "solidified"
    refreshed = store.get_code_skill(skill.skill_id)
    assert refreshed.active_version == 2


def test_repair_method_on_existing_skill(tmp_path):
    store = JsonCodeSkillStore(tmp_path / "store.json")
    llm = MockLLM([_spec("s6"), _good_code()])
    factory = NLCodeSkillFactory(llm, store)
    skill = factory.generate("brief")
    assert skill.active_version == 1

    # Ask the factory to repair: feed a fresh repair response
    factory.llm = MockLLM([_good_code()])
    repaired = factory.repair("s6", failure="user reported edge case x")
    assert repaired.active_version == 2
