"""Publication requires the deployed, fully rendered disclosure; it never grants old sessions."""

import importlib.util
import json
import os
import subprocess
import threading
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from dotenv import dotenv_values

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/deploy/elt_notice_publication.py"
SPEC = importlib.util.spec_from_file_location("elt_notice_publication", SCRIPT)
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


def rendered(documents, origin="https://example.com"):
    pages = {}
    links = [f"{origin}/login/legal/service-agreement", f"{origin}/login/legal/privacy-policy"]
    for key in ("service-agreement", "privacy-policy", "model-recipients"):
        doc = documents["privacy-policy" if key == "model-recipients" else key]
        sections = []
        for section in doc["sections"]:
            chunks = [section["title"]]
            for block in section["blocks"]:
                chunks.extend(
                    [block["paragraph"]] if "paragraph" in block else block.get("items", [])
                )
                if "table" in block:
                    table = block["table"]
                    chunks.extend([doc["title"], *table["columns"]])
                    chunks.extend(cell for row in table["rows"] for cell in row)
            sections.append("\n".join(chunks))
        pages[key] = {
            "title": doc["title"],
            "version": f"版本 {doc['version']} · 修订日期 {doc['updatedAt']}",
            "sections": sections,
            "policy_links": links,
        }
    pages["login_links"] = links
    return pages


def test_current_source_covers_both_versions_and_integrated_recipient():
    docs = publication.source_documents()
    assert set(docs) == {"service-agreement", "privacy-policy"}
    assert "token-plan-cn.xiaomimimo.com/v1" in json.dumps(docs, ensure_ascii=False)
    publication.verify_rendered(docs, rendered(docs), "https://example.com")


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://name:secret@example.com",
        "https://example.com/login",
        "https://example.com?key=secret",
        "https://example.com#part",
    ],
)
def test_refuses_non_origin_or_plain_http(origin):
    with pytest.raises(ValueError):
        publication.production_origin(origin)


@pytest.mark.parametrize("failure", ["shell", "version", "missing_disclosure", "alias", "links"])
def test_incomplete_or_stale_rendering_cannot_publish(failure):
    docs = publication.source_documents()
    pages = rendered(docs)
    if failure == "shell":
        pages = {"html": '<div id="app"></div>'}
    elif failure == "version":
        pages["privacy-policy"]["version"] = "版本 2020-01-01"
    elif failure == "missing_disclosure":
        pages["privacy-policy"]["sections"][3] = "模型接收方"
    elif failure == "alias":
        pages["model-recipients"]["title"] = "旧的独立接收方页面"
    else:
        pages["login_links"] = []
    with pytest.raises(ValueError):
        publication.verify_rendered(docs, pages, "https://example.com")


@pytest.mark.parametrize("location", ["login_links", "privacy-policy"])
def test_off_origin_policy_link_with_same_path_is_rejected(location):
    docs = publication.source_documents()
    pages = rendered(docs)
    target = pages if location == "login_links" else pages[location]
    target["login_links" if location == "login_links" else "policy_links"] = [
        "https://wrong.example/login/legal/service-agreement",
        "https://wrong.example/login/legal/privacy-policy",
    ]
    with pytest.raises(ValueError, match="outside the verified origin"):
        publication.verify_rendered(docs, pages, "https://example.com")


def test_install_preserves_secret_bytes_comments_and_multiline_values(tmp_path):
    env = tmp_path / "fhd.env"
    original = '# keep\r\nSECRET_KEY=private-test-value\r\nCERT="first\r\nFHD_ELT_NOTICE_PUBLICATION=inside-string\r\nlast"\r\n'
    env.write_bytes(original.encode())
    record = {
        "notice_version": "2026-11-01",
        "recipient_disclosure_version": "2026-11-01",
        "published_at": "2026-11-01T00:00:00+00:00",
    }
    publication.install_record(env, record)
    assert env.read_bytes().startswith(original.encode())
    assert json.loads(dotenv_values(env)[publication.ENV_KEY]) == record
    record["published_at"] = "2026-11-01T01:00:00+00:00"
    publication.install_record(env, record)
    assert env.read_bytes().startswith(original.encode())
    assert json.loads(dotenv_values(env)[publication.ENV_KEY]) == record


def test_duplicate_keys_leave_env_unchanged(tmp_path):
    env = tmp_path / "fhd.env"
    original = f"{publication.ENV_KEY}=old\nexport {publication.ENV_KEY}=other\n"
    env.write_text(original)
    with pytest.raises(ValueError):
        publication.install_record(env, {})
    assert env.read_text() == original


@pytest.mark.parametrize("target_flag", ["--env-file", "--record-file"])
def test_failed_live_verification_writes_no_record(monkeypatch, tmp_path, capsys, target_flag):
    env = tmp_path / "fhd.env"
    monkeypatch.setattr(publication, "render_policies", lambda *_: {})
    assert publication.main(["--origin", "https://example.com", target_flag, str(env)]) == 1
    assert not env.exists()
    assert publication.ENV_KEY not in capsys.readouterr().out


def test_success_has_only_strict_record_with_completion_time(monkeypatch, capsys):
    docs = publication.source_documents()
    monkeypatch.setattr(publication, "render_policies", lambda *_: rendered(docs))
    before = datetime.now(UTC)
    assert publication.main(["--origin", "https://example.com"]) == 0
    line = capsys.readouterr().out.strip()
    record = json.loads(line.removeprefix(f"{publication.ENV_KEY}="))
    assert set(record) == {"notice_version", "recipient_disclosure_version", "published_at"}
    assert before <= datetime.fromisoformat(record["published_at"]) <= datetime.now(UTC)


def test_record_file_is_genuinely_verified_strict_json(monkeypatch, tmp_path, capsys):
    docs = publication.source_documents()
    target = tmp_path / "elt_notice_publication.json"
    monkeypatch.setattr(publication, "render_policies", lambda *_: rendered(docs))
    before = datetime.now(UTC)
    assert publication.main(["--origin", "https://example.com", "--record-file", str(target)]) == 0
    record = json.loads(target.read_text(encoding="utf-8"))
    assert set(record) == {"notice_version", "recipient_disclosure_version", "published_at"}
    assert record["notice_version"] == docs["service-agreement"]["version"]
    assert record["recipient_disclosure_version"] == docs["privacy-policy"]["version"]
    assert before <= datetime.fromisoformat(record["published_at"]) <= datetime.now(UTC)
    assert "Verified nonsecret publication record written" in capsys.readouterr().out


def test_failed_record_replace_preserves_previous_file_and_reports_failure(
    monkeypatch, tmp_path, capsys
):
    docs = publication.source_documents()
    target = tmp_path / "elt_notice_publication.json"
    target.write_text("previous-record", encoding="utf-8")
    monkeypatch.setattr(publication, "render_policies", lambda *_: rendered(docs))

    def fail_replace(*_):
        raise PermissionError("synthetic access failure")

    monkeypatch.setattr(publication.os, "replace", fail_replace)
    assert publication.main(["--origin", "https://example.com", "--record-file", str(target)]) == 1
    assert target.read_text(encoding="utf-8") == "previous-record"
    assert not list(tmp_path.glob(".elt_notice_publication.json.*"))
    assert "Verified" not in capsys.readouterr().out


@pytest.mark.skipif(
    not os.environ.get("ELT_NOTICE_BROWSER_SMOKE"), reason="opt-in existing browser smoke"
)
@pytest.mark.parametrize("shell_only", [False, True])
def test_existing_browser_renders_synthetic_spa_and_rejects_shell(shell_only):
    docs = publication.source_documents()
    fixture = rendered(docs)

    class SyntheticPolicy(BaseHTTPRequestHandler):
        def do_GET(self):
            kind = self.path.rsplit("/", 1)[-1]
            if kind in fixture and not shell_only:
                page = fixture[kind]
                content = (
                    '<main class="login-legal"><article><nav><a href="/login/legal/service-agreement">协议</a><a href="/login/legal/privacy-policy">隐私</a></nav>'
                    + f"<h1>{escape(page['title'])}</h1><p>{escape(page['version'])}</p>"
                    + "".join(
                        f"<section>{escape(section)}</section>" for section in page["sections"]
                    )
                    + "</article></main>"
                )
            else:
                content = '<a href="/login/legal/service-agreement">协议</a><a href="/login/legal/privacy-policy">隐私</a>'
            # Initial HTML alone is deliberately insufficient; the helper must wait for rendering.
            html = f'<html><body><div id="app"></div><script>setTimeout(() => document.getElementById("app").innerHTML = {json.dumps(content)}, 100)</script></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SyntheticPolicy)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        result = subprocess.run(
            [
                "node",
                str(SCRIPT.with_suffix(".mjs")),
                f"http://127.0.0.1:{server.server_port}",
                os.environ["ELT_NOTICE_BROWSER_SMOKE"],
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=100,
        )
        if shell_only:
            assert result.returncode != 0
        else:
            assert result.returncode == 0, result.stderr
            publication.verify_rendered(
                docs, json.loads(result.stdout), f"http://127.0.0.1:{server.server_port}"
            )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
