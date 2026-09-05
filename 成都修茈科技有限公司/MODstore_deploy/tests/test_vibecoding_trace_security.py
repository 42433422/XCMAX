from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from modstore_server.llm_crypto import decrypt_secret
from modstore_server.vibecoding_convert_loop import write_codegen_trace


def test_codegen_trace_encrypts_private_content_and_uses_owner_only_files(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))

    write_codegen_trace(
        tmp_path,
        session_id="session-1",
        round_no=2,
        convert_py="PRIVATE_CUSTOMER_CODE = True",
        meta={"brief": "private customer brief"},
        smoke={"sample": "private smoke data"},
        golden={"sample": "private golden data"},
    )

    files = sorted((tmp_path / "session-1").glob("round_2_*.enc.json"))
    assert len(files) == 4
    for path in files:
        stored = path.read_text(encoding="utf-8")
        envelope = json.loads(stored)
        assert envelope["schema"] == "xcagi.vibecoding_trace.encrypted/v1"
        assert "private" not in stored.lower()
        assert path.stat().st_mode & 0o777 == 0o600
        assert decrypt_secret(envelope["ciphertext"])


def test_codegen_trace_rejects_session_path_traversal(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MODSTORE_LLM_MASTER_KEY", Fernet.generate_key().decode("ascii"))

    with pytest.raises(ValueError, match="invalid vibecoding trace session_id"):
        write_codegen_trace(
            tmp_path,
            session_id="../escape",
            round_no=0,
            convert_py="pass",
            meta={},
            smoke={},
            golden={},
        )

    assert not (tmp_path.parent / "escape").exists()
