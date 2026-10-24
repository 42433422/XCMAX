"""能力中心详情页：截图 / 录像原件经私有 COS 预签名读取，并保留站内回退与哈希核验。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[3]
SITE = ROOT / "成都修茈科技有限公司"
SCRIPT = SITE / "scripts/build_capability_center.py"
SPEC = importlib.util.spec_from_file_location("build_capability_center_cos", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

API = "/api/public/evidence/"
INDEX = json.loads((SITE / "data/capabilities/evidence-index.json").read_text(encoding="utf-8"))[
    "assets"
]


@pytest.fixture(scope="module", autouse=True)
def rebuild_publication_files():
    MODULE.prepare_evidence_assets()


def test_media_routes_through_backend_and_other_files_stay_local(tmp_path, monkeypatch) -> None:
    MODULE._EVIDENCE_INDEX.clear()
    # 媒体已外置：用临时 png 验证 COS 登记路径；缺失源文件仍回退站内路径。
    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "e", lambda rel: tmp_path / rel)
    png_rel = "FHD/docs/evidence/capabilities/ai-employee-pack-01-employee-market.png"
    png_path = tmp_path / png_rel
    png_path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"fake-evidence-png"
    png_path.write_bytes(payload)
    MODULE._SHA_CACHE.clear()
    assert MODULE.evidence_url("x-shot.png", png_rel) == API + "x-shot.png"
    assert MODULE._EVIDENCE_INDEX["x-shot.png"]["key"] == png_rel
    assert MODULE._EVIDENCE_INDEX["x-shot.png"]["sha256"] == hashlib.sha256(payload).hexdigest()
    # JSON / 日志不进桶，仍由站内提供；缺失的源文件也不登记。
    json_rel = "成都修茈科技有限公司/capabilities/assets/evidence/sample-run.json"
    json_path = tmp_path / json_rel
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("{}", encoding="utf-8")
    assert MODULE.evidence_url("x.json", json_rel) == "/capabilities/assets/evidence/x.json"
    assert (
        MODULE.evidence_url("gone.png", "FHD/docs/evidence/does-not-exist.png")
        == "/capabilities/assets/evidence/gone.png"
    )
    MODULE._EVIDENCE_INDEX.clear()
    MODULE._SHA_CACHE.clear()


def test_cos_key_uses_repo_path_or_public_copy() -> None:
    assert (
        MODULE.evidence_cos_key("FHD/docs/evidence/e2e/a.png", "f-a.png")
        == "FHD/docs/evidence/e2e/a.png"
    )

    assert (
        MODULE.evidence_cos_key("docs/elsewhere/a.png", "f-a.png")
        == "成都修茈科技有限公司/capabilities/assets/evidence/f-a.png"
    )


def test_external_provenance_is_not_read_as_a_repository_file() -> None:
    url = "https://xiu-ci.com/download-release.json"
    assert MODULE.evidence_paths({"release": url}) == set()
    assert MODULE.privacy_exclusions({"release": url}) == set()
    assert not MODULE.path_exists(url)
    assert not MODULE.path_exists("")


def test_windows_receipts_resolve_without_generated_files(tmp_path, monkeypatch) -> None:
    expected = MODULE.windows_delivery_panel()
    monkeypatch.setattr(MODULE, "EVIDENCE_ASSET_DIR", tmp_path / "absent")
    assert MODULE.windows_delivery_panel() == expected
    assert not MODULE.EVIDENCE_ASSET_DIR.exists()


def _page_refs() -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for page in sorted((SITE / "capabilities/feature").glob("*.html")):
        html = page.read_text(encoding="utf-8")
        for attr, url in re.findall(r'\b(src|href)="(/api/public/evidence/[^"]+)"', html):
            refs.setdefault(unquote(url[len(API) :]), set()).add(page.name)
    return refs


def test_every_backend_evidence_link_is_indexed_and_has_matching_local_fallback() -> None:
    refs = _page_refs()
    assert refs, "详情页应通过后端读取证据原件"
    assert set(refs) == set(INDEX), "页面引用与证据白名单必须一一对应"
    pointer = SITE / "capabilities/assets/evidence" / "ARCHIVE_POINTER.md"
    archived = pointer.is_file()
    for name, entry in INDEX.items():
        assert entry.get("sha256") and entry.get("size"), name
        assert len(entry["sha256"]) == 64, name
        local = SITE / "capabilities/assets/evidence" / name
        if not local.is_file():
            # 2026-10-25：媒体已外置；白名单 + COS 预签名仍是权威，本地回退可选。
            assert archived, f"missing local fallback without archive pointer: {name}"
            continue
        raw = local.read_bytes()
        assert len(raw) == entry["size"], name
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], name


def test_detail_pages_show_originals_playable_video_and_hash_controls() -> None:
    for page in sorted((SITE / "capabilities/feature").glob("*.html")):
        html = page.read_text(encoding="utf-8")
        if API not in html:
            continue
        assert "/capabilities/assets/evidence.js?v=" in html, page.name
        for video in re.findall(r"<video[^>]*>", html):
            assert "controls" in video and "playsinline" in video, page.name
        for name, sha in re.findall(r'data-evidence="([^"]+)" data-sha256="([0-9a-f]{64})"', html):
            assert INDEX[name]["sha256"] == sha, (page.name, name)
            assert f"<code>{sha}</code>" in html, (page.name, name)
        # 截图链接与 <img> 指向同一原件，不提供缩略图替身。
        for href, src in re.findall(
            r'<a class="cap-shot-link" href="([^"]+)"[^>]*><img src="([^"]+)"', html
        ):
            assert href == src and href.startswith(API), page.name


def test_public_whitelist_does_not_restore_withdrawn_customer_evidence() -> None:
    private = ("base-login-", "ind-attendance-", "erp-sales-order-", "ind-szqsm-")
    assert not [name for name in INDEX if name.startswith(private)]
    assert not any(
        marker in json.dumps(INDEX, ensure_ascii=False).casefold()
        for marker in MODULE._PUBLIC_PRIVATE_MARKERS
    )
    cases = json.loads((ROOT / "FHD/config/public_cases.json").read_text())["cases"]
    assert cases == []


@pytest.fixture
def private_run(tmp_path, monkeypatch):
    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "CATALOG_PATH", tmp_path / "catalog.json")
    monkeypatch.setattr(MODULE, "EVIDENCE_ASSET_DIR", tmp_path / "public")
    MODULE.EVIDENCE_ASSET_DIR.mkdir()
    run = {
        "platform": "windows",
        "status": "passed",
        "verdict": "PASS",
        "passed": 9,
        "failed": 0,
        "app_version": "1.0.0.5",
        "app_git_sha": "b" * 40,
        "verified_at": "2026-09-29T08:00:00Z",
        "_acceptance_path": "run.json",
        "_acceptance_sha256": "c" * 64,
        "account": "sunbird",
        "media": [{"path": "private/shot.png"}, {"path": "private/flow.mp4"}],
        "log": {"path": "run.log"},
    }
    (tmp_path / "run.json").write_text(json.dumps(run))
    feature = {
        "id": "base-health",
        "platforms": ["windows"],
        "evidence": {
            "runs": ["run.json"],
            "platform_assets": {
                "windows": {
                    "acceptance": {"path": "run.json"},
                    "identity": {"path": "identity.json"},
                },
                "macos": {"acceptance": {"path": "public.json"}, "raw": ["public-identity.json"]},
            },
        },
    }
    module = {"features": [feature]}
    catalog = {"domains": [{"modules": [module]}]}
    MODULE.CATALOG_PATH.write_text(json.dumps(catalog))
    return feature, run


def test_withdrawn_run_excludes_companion_media_and_platform_identity(private_run) -> None:
    feature, run = private_run
    excluded = MODULE.privacy_exclusions(feature["evidence"], feature["id"])
    assert excluded == {
        "run.json",
        "private/shot.png",
        "private/flow.mp4",
        "run.log",
        "identity.json",
    }
    assert MODULE.public_projection({"media": run["media"]}, excluded)["media"] == []


def test_withdrawn_run_retains_only_exact_historical_identity(private_run, monkeypatch) -> None:
    feature, run = private_run
    monkeypatch.setattr(MODULE, "traceable_pass", lambda *args: (True, "a" * 64))
    monkeypatch.setattr(MODULE, "platform_observations", lambda *args: [])
    monkeypatch.setattr(MODULE, "path_exists", lambda *args: True)
    public = MODULE.public_projection(MODULE.platform_verdicts(feature, [run], []), {"run.json"})
    assert public[0]["runs"] == []
    assert public[0]["run_identities"] == [
        {
            k: run[k]
            for k in (
                "app_version",
                "app_git_sha",
                "verified_at",
                "verdict",
                "passed",
                "failed",
                "_acceptance_sha256",
            )
        }
    ]
    assert "sunbird" not in json.dumps(public).casefold()


def test_withdrawn_run_does_not_redact_same_named_public_platform_media() -> None:
    value = {"media": [{"path": "public/shot.png"}, {"path": "private/shot.png"}]}
    assert MODULE.public_projection(value, {"private/shot.png"}) == {
        "media": [{"path": "public/shot.png"}]
    }


def test_withdrawn_run_preserves_only_matching_public_fallback(private_run, monkeypatch) -> None:
    public = MODULE.EVIDENCE_ASSET_DIR / "base-health-shot.png"
    public.write_bytes(b"approved public media")
    monkeypatch.setattr(
        MODULE,
        "_EVIDENCE_INDEX",
        {public.name: {"sha256": hashlib.sha256(public.read_bytes()).hexdigest()}},
    )
    assert MODULE.private_generated_assets() == []
    public.write_bytes(b"unapproved replacement")
    assert MODULE.private_generated_assets() == [public]
