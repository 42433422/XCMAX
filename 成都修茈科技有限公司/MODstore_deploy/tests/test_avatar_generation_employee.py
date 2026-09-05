from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

from cryptography.fernet import Fernet

from modstore_server.llm_crypto import decrypt_secret

ROOT = Path(__file__).resolve().parents[1]
EMPLOYEE_ENTRY = (
    ROOT
    / "library"
    / "avatar-generation-employee"
    / "backend"
    / "employees"
    / "avatar_generation_employee.py"
)


def _load_employee_module():
    spec = importlib.util.spec_from_file_location("avatar_generation_employee_test", EMPLOYEE_ENTRY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_avatar_generation_employee_covers_all_human_avatar_types(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    module = _load_employee_module()
    result = asyncio.run(
        module.run(
            {
                "employee_name": "小 C 助理",
                "employee_role": "企业 AI 助手",
                "department": "超级开发部",
                "style": "clean anime, premium SaaS",
                "generate_image": False,
                "workspace_root": str(tmp_path),
            },
            {"workspace_root": str(tmp_path)},
        )
    )

    assert result["ok"] is True
    payload = result["items"][0]
    profile = payload["profile"]
    labels = {row["label"] for row in profile["taxonomy"]}
    assert labels == {
        "真人头像",
        "关系型头像",
        "动漫/游戏/虚拟角色",
        "插画化本人",
        "职业/品牌型头像",
        "动物/宠物/吉祥物",
        "兴趣符号型",
        "抽象/氛围型",
        "默认/极简型",
    }
    assert profile["avatar_type"] == "anime_game"
    assert profile["prompt_preset"]["id"] == "xiaoc_human_aquatic"
    assert "human-like" in profile["prompt_en"]
    assert "no animal face" in profile["prompt_en"]
    output_path = tmp_path / "outputs" / "avatar_profile.json"
    assert output_path.is_file()
    envelope = json.loads(output_path.read_text(encoding="utf-8"))
    assert envelope["schema"] == "xcagi.avatar_profile.encrypted/v1"
    persisted = json.loads(decrypt_secret(envelope["ciphertext"]))
    assert persisted["profile"]["employee_name"] == "小 C 助理"
    assert "小 C 助理" not in output_path.read_text(encoding="utf-8")
    assert output_path.stat().st_mode & 0o777 == 0o600
    assert payload["outputs"]["profile_json_encrypted"] is True


def test_avatar_generation_employee_presets_batch_avatar_sheet(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    module = _load_employee_module()
    result = asyncio.run(
        module.run(
            {
                "task": "给每个 AI 员工生成一组头像表，4x3 批量裁切",
                "generate_image": False,
                "workspace_root": str(tmp_path),
            },
            {"workspace_root": str(tmp_path)},
        )
    )

    assert result["ok"] is True
    profile = result["items"][0]["profile"]
    assert profile["prompt_preset"]["id"] == "employee_avatar_sheet"
    assert "exact 4 columns x 3 rows sprite sheet" in profile["prompt_en"]
    assert "按 4x3 网格裁切" in profile["prompt_preset"]["postprocess"]
    assert {p["id"] for p in profile["prompt_preset_catalog"]} == {
        "employee_avatar_sheet",
        "xiaoc_human_aquatic",
        "mobile_contact_avatar",
    }


def test_avatar_generation_rejects_payload_selected_output_escape(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    module = _load_employee_module()
    outside = tmp_path.parent / "avatar-escape.json"

    result = asyncio.run(
        module.run(
            {
                "output_relpath": str(outside),
                "workspace_root": str(tmp_path.parent),
                "generate_image": False,
            },
            {"workspace_root": str(tmp_path)},
        )
    )

    assert result["ok"] is False
    assert "employee workspace" in result["error"]
    assert not outside.exists()


def test_avatar_generation_fails_closed_without_encryption_key(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("MODSTORE_LLM_MASTER_KEY", raising=False)
    module = _load_employee_module()

    result = asyncio.run(
        module.run(
            {"generate_image": False},
            {"workspace_root": str(tmp_path)},
        )
    )

    assert result["ok"] is False
    assert "MASTER_KEY" in result["error"]
    assert not (tmp_path / "outputs" / "avatar_profile.json").exists()
