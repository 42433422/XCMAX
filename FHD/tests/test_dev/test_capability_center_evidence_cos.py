"""能力中心详情页：截图 / 录像原件经私有 COS 预签名读取，并保留站内回退与哈希核验。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from urllib.parse import unquote

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


def test_media_routes_through_backend_and_other_files_stay_local() -> None:
    MODULE._EVIDENCE_INDEX.clear()
    png = "FHD/docs/evidence/capabilities/ai-employee-pack-01-employee-market.png"
    assert MODULE.evidence_url("x-shot.png", png) == API + "x-shot.png"
    assert MODULE._EVIDENCE_INDEX["x-shot.png"]["key"] == png
    assert (
        MODULE._EVIDENCE_INDEX["x-shot.png"]["sha256"]
        == hashlib.sha256((ROOT / png).read_bytes()).hexdigest()
    )
    # JSON / 日志不进桶，仍由站内提供；缺失的源文件也不登记。
    run_json = next(SITE.glob("capabilities/assets/evidence/*.json")).relative_to(ROOT).as_posix()
    assert MODULE.evidence_url("x.json", run_json) == "/capabilities/assets/evidence/x.json"
    assert (
        MODULE.evidence_url("gone.png", "FHD/docs/evidence/does-not-exist.png")
        == "/capabilities/assets/evidence/gone.png"
    )
    MODULE._EVIDENCE_INDEX.clear()


def test_cos_key_uses_repo_path_or_public_copy() -> None:
    assert (
        MODULE.evidence_cos_key("FHD/docs/evidence/e2e/a.png", "f-a.png")
        == "FHD/docs/evidence/e2e/a.png"
    )
    assert (
        MODULE.evidence_cos_key("docs/elsewhere/a.png", "f-a.png")
        == "成都修茈科技有限公司/capabilities/assets/evidence/f-a.png"
    )


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
    for name, entry in INDEX.items():
        local = SITE / "capabilities/assets/evidence" / name
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
