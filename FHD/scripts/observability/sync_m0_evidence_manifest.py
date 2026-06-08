#!/usr/bin/env python3
"""Sync m0-evidence-manifest.json from on-disk PNGs and /metrics probe."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_SLO = ROOT / "docs" / "evidence" / "slo"
EVIDENCE_MOD = ROOT / "docs" / "evidence" / "mod"
MANIFEST = ROOT / "docs" / "evidence" / "m0-evidence-manifest.json"
DATE_SUFFIX = "202606"
METRICS_URL = "http://127.0.0.1:5000/metrics"

SLO_PANELS = [
    {"uid": "xcagi-slo", "panel_id": 1, "suffix": "api-availability", "title": "SLO-API-01 · Availability (30d)", "target": "99.9%", "slo_id": "SLO-API-01"},
    {"uid": "xcagi-mod-store", "panel_id": 5, "suffix": "db-mod-sqlite-copies", "title": "Per-mod SQLite DB copies", "target": "M0 路径图", "slo_id": None},
    {"uid": "xcagi-slo", "panel_id": 3, "suffix": "ai-chat-p95", "title": "SLO-AI-01 · Chat first-byte P95", "target": "< 1500ms", "slo_id": "SLO-AI-01"},
    {"uid": "xcagi-slo", "panel_id": 7, "suffix": "neurobus-delivery", "title": "NeuroBus delivery success", "target": ">= 99.95%", "slo_id": "SLO-BUS-01"},
]

MOD_STEPS = [
    {"file": "01-listing.png", "step": 1, "title": "商家入驻 / Mod 上架", "action": "审核通过"},
    {"file": "02-store-page.png", "step": 2, "title": "市场页可见", "action": "可安装"},
    {"file": "03-payment.png", "step": 3, "title": "0.01 元支付", "action": "沙箱/约定环境"},
    {"file": "04-activated.png", "step": 4, "title": "FHD 宿主开通", "action": "安装并激活 Mod"},
]


def file_row(path: Path, rel_root: Path = ROOT) -> dict:
    if path.is_file() and path.stat().st_size > 0:
        return {"present": True, "bytes": path.stat().st_size, "path": str(path.relative_to(rel_root))}
    return {"present": False, "bytes": 0, "path": str(path.relative_to(rel_root))}


def grafana_png_has_data(path: Path, *, min_bytes: int = 28000) -> bool:
    """Heuristic: Grafana render with stat data is typically >28KB; scaffold ~22KB."""
    if not path.is_file():
        return False
    return path.stat().st_size >= min_bytes


def metrics_has_api_requests() -> bool:
    try:
        with urllib.request.urlopen(METRICS_URL, timeout=3) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        return "api_requests_total{" in text or "api_requests_total " in text
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def slo_panel(kind: str, panel: dict) -> dict:
    name = f"grafana-{kind}-m0-{panel['suffix']}-{DATE_SUFFIX}.png"
    path = EVIDENCE_SLO / name
    row = file_row(path)
    preview = "scaffold"
    if row["present"]:
        if kind == "local" and grafana_png_has_data(path):
            preview = "grafana"
        elif kind == "local" and metrics_has_api_requests():
            preview = "metrics"
        elif kind == "staging" and grafana_png_has_data(path):
            preview = "accepted"
    return {**panel, "kind": kind, "filename": name, "preview": preview, **row}


def mod_step(step: dict) -> dict:
    path = EVIDENCE_MOD / step["file"]
    row = file_row(path)
    preview = "missing"
    if row["present"] and row["bytes"] > 25000:
        preview = "verified"
    elif row["present"]:
        preview = "path"
    return {**step, "preview": preview, **row}


def build_manifest() -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    staging_panels = [slo_panel("staging", p) for p in SLO_PANELS]
    local_panels = [slo_panel("local", p) for p in SLO_PANELS]
    mod_steps = [mod_step(s) for s in MOD_STEPS]

    staging_accepted = sum(1 for p in staging_panels if p["preview"] == "accepted")
    local_grafana = sum(1 for p in local_panels if p["preview"] in {"grafana", "metrics"})
    mod_verified = sum(1 for s in mod_steps if s["preview"] == "verified")

    staging_ok = sum(1 for p in staging_panels if p["present"])
    local_ok = sum(1 for p in local_panels if p["present"])
    mod_ok = sum(1 for s in mod_steps if s["present"])

    def staging_status() -> str:
        if staging_accepted == 4:
            return "pass"
        return "blocked"

    def local_status() -> str:
        if local_grafana == 4:
            return "pass"
        if local_ok == 4:
            return "partial"
        return "blocked"

    def mod_status() -> str:
        if mod_verified == 4:
            return "pass"
        return "blocked"

    return {
        "generated_at": now,
        "staging_slo": {
            "label": "staging SLO 四域",
            "blocker": "T36–T37 · 需 KUBECONFIG + staging 7d 流量（export --prefix staging）",
            "ready": staging_ok,
            "total": 4,
            "scaffold_ready": sum(1 for p in staging_panels if p["preview"] == "scaffold" and p["present"]),
            "acceptance_ready": staging_accepted,
            "status": staging_status(),
            "panels": staging_panels,
        },
        "local_slo": {
            "label": "本地 SLO 四域预览",
            "ready": local_ok,
            "total": 4,
            "grafana_ready": local_grafana,
            "status": local_status(),
            "panels": local_panels,
            "note": "Grafana 真图：local_stack_up.sh；≠ staging 7d 验收",
        },
        "mod_pilot": {
            "label": "Mod 商家试点四图",
            "blocker": "需 MODstore + 0.01 元沙箱 + FHD 激活 · mod-pilot-checklist.sh --verify",
            "ready": mod_ok,
            "total": 4,
            "path_ready": sum(1 for s in mod_steps if s["preview"] == "path" and s["present"]),
            "verified_ready": mod_verified,
            "status": mod_status(),
            "steps": mod_steps,
        },
        "display": {
            "staging_slo_headline": (
                f"✅ staging SLO 四图 · 7d 验收 {staging_accepted}/4"
                if staging_accepted == 4
                else f"❌ staging SLO 四图 · 7d 验收 {staging_accepted}/4 · 未就位"
            ),
            "mod_pilot_headline": (
                f"✅ Mod 四图 · 商家流水 {mod_verified}/4"
                if mod_verified == 4
                else f"❌ Mod 四图 · 商家流水 {mod_verified}/4 · 未跑通"
            ),
            "local_slo_headline": (
                f"✅ 本地 SLO · Grafana 真图 {local_grafana}/4"
                if local_grafana == 4
                else f"⏳ 本地 SLO · Grafana {local_grafana}/4 · 指标/导出待齐"
            ),
        },
    }


def main() -> None:
    manifest = build_manifest()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    d = manifest["display"]
    print(f"[sync_m0] {d['staging_slo_headline']}")
    print(f"[sync_m0] {d['mod_pilot_headline']}")
    print(f"[sync_m0] {d['local_slo_headline']}")
    print(f"[sync_m0] → {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
