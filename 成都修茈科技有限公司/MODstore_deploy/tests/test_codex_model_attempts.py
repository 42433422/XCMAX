"""Codex 模型网关在 MODstore 侧：派发提示带候选模型、失败回写尝试过的模型。"""

from __future__ import annotations

from modstore_server.codex_model_attempts import (
    codex_model_candidates_line,
    parse_codex_models_tried,
)
from modstore_server.incident_team_handler_digest import handler_output_digest
from modstore_server.para_delegate_handler import _build_para_prompt


def test_candidates_line_from_env_and_request(monkeypatch):
    monkeypatch.delenv("MODSTORE_PARA_CODEX_MODEL_CANDIDATES", raising=False)
    assert codex_model_candidates_line({}) == ""
    monkeypatch.setenv(
        "MODSTORE_PARA_CODEX_MODEL_CANDIDATES", "gpt-5.6-sol, gpt-5.6-terra>gpt-5.6-luna"
    )
    assert (
        codex_model_candidates_line({})
        == "- codex_model_candidates: gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna"
    )
    line = codex_model_candidates_line({"codex_model_candidates": ["x", "bad value;rm", "x"]})
    assert line == "- codex_model_candidates: x"


def test_para_prompt_carries_candidates(monkeypatch):
    monkeypatch.setenv("MODSTORE_PARA_CODEX_MODEL_CANDIDATES", "gpt-5.6-sol,gpt-5.6-terra")
    prompt = _build_para_prompt({"prompt": "修复工单", "mode": "code"})
    assert "- codex_model_candidates: gpt-5.6-sol,gpt-5.6-terra" in prompt
    monkeypatch.delenv("MODSTORE_PARA_CODEX_MODEL_CANDIDATES")
    assert "codex_model_candidates" not in _build_para_prompt({"prompt": "修复工单"})


def test_parse_models_tried_from_failure_text():
    text = (
        "[e2e-agent] [codex_models_tried=gpt-5.6-sol:unsupported,gpt-5.6-terra:quota] "
        "Codex CLI 非零退出: ... codex_models_tried=gpt-5.6-sol:unsupported,gpt-5.6-terra:quota"
    )
    assert parse_codex_models_tried(None, text) == [
        {"model": "gpt-5.6-sol", "status": "unsupported"},
        {"model": "gpt-5.6-terra", "status": "quota"},
    ]
    assert parse_codex_models_tried("no marker", "") == []
    assert parse_codex_models_tried("codex_models_tried=a:weird") == []


def test_digest_keeps_models_tried_without_secrets():
    digest = handler_output_digest(
        {
            "result": {
                "outputs": [
                    {
                        "handler": "para_delegate",
                        "ok": False,
                        "error": "token=abc failed",
                        "codex_models_tried": [
                            {"model": "gpt-5.6-sol", "status": "skipped"},
                            {"model": "gpt-5.6-terra", "status": "unsupported"},
                        ],
                    }
                ]
            }
        }
    )
    row = digest["outputs"][0]
    assert row["codex_models_tried"] == [
        {"model": "gpt-5.6-sol", "status": "skipped"},
        {"model": "gpt-5.6-terra", "status": "unsupported"},
    ]
    assert "abc" not in row["error"]
