#!/usr/bin/env python3
"""Render M0 SLO panel preview PNGs (Grafana-style, no fake metrics).

Outputs to docs/evidence/slo/ and updates docs/evidence/m0-evidence-manifest.json.
Local previews read live /metrics when FastAPI is up; otherwise show scaffold text.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_SLO = ROOT / "docs" / "evidence" / "slo"
EVIDENCE_MOD = ROOT / "docs" / "evidence" / "mod"
MANIFEST = ROOT / "docs" / "evidence" / "m0-evidence-manifest.json"
METRICS_URL = "http://127.0.0.1:5000/metrics"
SLA_SNAPSHOT = ROOT / "metrics" / "sla-snapshot.json"
DATE_SUFFIX = "202606"

SLO_PANELS = [
    {
        "uid": "xcagi-slo",
        "panel_id": 1,
        "suffix": "api-availability",
        "title": "SLO-API-01 · Availability (30d)",
        "target": "99.9%",
        "slo_id": "SLO-API-01",
    },
    {
        "uid": "xcagi-mod-store",
        "panel_id": 5,
        "suffix": "db-mod-sqlite-copies",
        "title": "Per-mod SQLite DB copies",
        "target": "M0 路径图",
        "slo_id": None,
    },
    {
        "uid": "xcagi-slo",
        "panel_id": 3,
        "suffix": "ai-chat-p95",
        "title": "SLO-AI-01 · Chat first-byte P95",
        "target": "< 1500ms",
        "slo_id": "SLO-AI-01",
    },
    {
        "uid": "xcagi-slo",
        "panel_id": 7,
        "suffix": "neurobus-delivery",
        "title": "NeuroBus delivery success",
        "target": ">= 99.95%",
        "slo_id": "SLO-BUS-01",
    },
]

MOD_STEPS = [
    {"file": "01-listing.png", "step": 1, "title": "商家入驻 / Mod 上架", "action": "审核通过"},
    {"file": "02-store-page.png", "step": 2, "title": "市场页可见", "action": "可安装"},
    {"file": "03-payment.png", "step": 3, "title": "0.01 元支付", "action": "沙箱/约定环境"},
    {"file": "04-activated.png", "step": 4, "title": "FHD 宿主开通", "action": "安装并激活 Mod"},
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def fetch_metrics_text(url: str = METRICS_URL) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


def _parse_counter_lines(text: str, name: str) -> list[tuple[dict[str, str], float]]:
    rows: list[tuple[dict[str, str], float]] = []
    pat = re.compile(rf"^{re.escape(name)}(\{{([^}}]*)\}})? (\S+)")
    for line in text.splitlines():
        m = pat.match(line.strip())
        if not m:
            continue
        labels_raw = m.group(2) or ""
        labels: dict[str, str] = {}
        for part in labels_raw.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                labels[k.strip()] = v.strip().strip('"')
        rows.append((labels, float(m.group(3))))
    return rows


def _parse_gauge_lines(text: str, name: str) -> list[tuple[dict[str, str], float]]:
    return _parse_counter_lines(text, name)


def _histogram_p95_ms(text: str, name: str) -> float | None:
    buckets: dict[float, float] = {}
    total = 0.0
    for labels, val in _parse_counter_lines(text, f"{name}_bucket"):
        le = labels.get("le")
        if le is None:
            continue
        bound = float("inf") if le == "+Inf" else float(le)
        buckets[bound] = buckets.get(bound, 0.0) + val
    for _, val in _parse_counter_lines(text, f"{name}_count"):
        total += val
    if total <= 0 or not buckets:
        return None
    target = total * 0.95
    running = 0.0
    for le in sorted(buckets):
        running += buckets[le]
        if running >= target:
            return le * 1000.0
    return None


def _sla_baseline(slo_id: str) -> str | None:
    if not SLA_SNAPSHOT.is_file():
        return None
    try:
        snap = json.loads(SLA_SNAPSHOT.read_text(encoding="utf-8"))
        for row in snap.get("slos") or []:
            if row.get("id") == slo_id and row.get("baseline"):
                return str(row["baseline"]).strip()
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


def load_local_metric_values() -> dict[str, float | int | None]:
    text = fetch_metrics_text()
    out: dict[str, float | int | None] = {
        "api_availability": None,
        "ai_chat_p95_ms": None,
        "mod_sqlite_ready": None,
        "neurobus_delivery": None,
        "metrics_live": bool(text),
    }
    if text:
        api_rows = _parse_counter_lines(text, "api_requests_total")
        if api_rows:
            total = sum(v for _, v in api_rows)
            err = sum(v for labels, v in api_rows if str(labels.get("status", "")).startswith("5"))
            out["api_availability"] = 1.0 - (err / total) if total else None

        out["ai_chat_p95_ms"] = _histogram_p95_ms(text, "chat_stream_first_byte_seconds")

        mod_rows = _parse_gauge_lines(text, "mod_sqlite_copy_present")
        if mod_rows:
            out["mod_sqlite_ready"] = sum(1 for _, v in mod_rows if v >= 1.0)

        pub = sum(v for _, v in _parse_counter_lines(text, "neurobus_events_published_total"))
        lost = sum(v for _, v in _parse_counter_lines(text, "neurobus_events_lost_total"))
        dlq = sum(v for _, v in _parse_counter_lines(text, "neurobus_events_dead_lettered_total"))
        if pub > 0:
            out["neurobus_delivery"] = 1.0 - ((lost + dlq) / pub)

    if out["api_availability"] is None:
        baseline = _sla_baseline("SLO-API-01")
        if baseline:
            out["api_availability"] = float(baseline.rstrip("%")) / 100.0

    if out["ai_chat_p95_ms"] is None:
        baseline = _sla_baseline("SLO-AI-01")
        if baseline:
            out["ai_chat_p95_ms"] = float(baseline.rstrip("ms"))

    if out["neurobus_delivery"] is None:
        baseline = _sla_baseline("SLO-BUS-01")
        if baseline:
            out["neurobus_delivery"] = float(baseline.rstrip("%")) / 100.0

    return out


def _format_stat(value: float | int, panel: dict) -> tuple[str, str]:
    suffix = panel.get("suffix", "")
    if suffix == "api-availability" or suffix == "neurobus-delivery":
        return f"{value * 100:.2f}%", "#73bf69"
    if suffix == "ai-chat-p95":
        return f"{value:.0f} ms", "#73bf69" if float(value) < 1500 else "#ff9830"
    if suffix == "db-mod-sqlite-copies":
        return str(int(value)), "#5794f2"
    return str(value), "#d8d9da"


def _panel_stat_value(panel: dict, metrics: dict[str, float | int | None]) -> tuple[str, str] | None:
    suffix = panel.get("suffix", "")
    if suffix == "api-availability" and metrics.get("api_availability") is not None:
        return _format_stat(float(metrics["api_availability"]), panel)
    if suffix == "ai-chat-p95" and metrics.get("ai_chat_p95_ms") is not None:
        return _format_stat(float(metrics["ai_chat_p95_ms"]), panel)
    if suffix == "db-mod-sqlite-copies" and metrics.get("mod_sqlite_ready") is not None:
        return _format_stat(int(metrics["mod_sqlite_ready"]), panel)
    if suffix == "neurobus-delivery" and metrics.get("neurobus_delivery") is not None:
        return _format_stat(float(metrics["neurobus_delivery"]), panel)
    return None


def render_slo_preview(panel: dict, dest: Path, *, mode: str = "local", metrics: dict | None = None) -> None:
    w, h = 1200, 600
    img = Image.new("RGB", (w, h), "#111217")
    draw = ImageDraw.Draw(img)
    title_font = _font(28, bold=True)
    sub_font = _font(18)
    mono_font = _font(16)
    small_font = _font(14)

    draw.rectangle([0, 0, w, 52], fill="#181b1f", outline="#2c3235")
    draw.text((16, 14), panel["title"], fill="#d8d9da", font=title_font)

    badge = f'{panel["uid"]}:{panel["panel_id"]}'
    bbox = draw.textbbox((0, 0), badge, font=small_font)
    bw = bbox[2] - bbox[0] + 16
    draw.rounded_rectangle([w - bw - 12, 12, w - 12, 40], radius=4, fill="#2c3235", outline="#464c54")
    draw.text((w - bw - 4, 16), badge, fill="#8e8e8e", font=small_font)

    draw.line([(24, 80), (w - 24, 80)], fill="#2c3235", width=1)
    stat = _panel_stat_value(panel, metrics or {}) if mode == "local" else None
    if stat:
        value_text, value_color = stat
        val_font = _font(96, bold=True)
        bbox = draw.textbbox((0, 0), value_text, font=val_font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, h // 2 - 72), value_text, fill=value_color, font=val_font)
        sub = "live /metrics" if (metrics or {}).get("metrics_live") else "SSOT baseline"
        draw.text((w // 2 - 180, h // 2 + 36), sub, fill="#8e8e8e", font=mono_font)
    elif mode == "staging":
        draw.text((w // 2 - 140, h // 2 - 48), "Staging scaffold", fill="#ffa657", font=sub_font)
        draw.text(
            (w // 2 - 260, h // 2 - 8),
            "Grafana JSON + Helm values-staging wired · no 7d traffic yet",
            fill="#484f58",
            font=mono_font,
        )
    else:
        draw.text((w // 2 - 120, h // 2 - 48), "No data", fill="#6e7681", font=sub_font)
        draw.text(
            (w // 2 - 200, h // 2 - 8),
            "Restart FastAPI + local_stack_up.sh export",
            fill="#484f58",
            font=mono_font,
        )
    draw.text((w // 2 - 80, h // 2 + 32 if stat else h // 2 + 32), f'Target: {panel["target"]}', fill="#58e2c2", font=mono_font)

    draw.rectangle([0, h - 36, w, h], fill="#0b0c0e")
    footer = (
        "STAGING SCAFFOLD · dashboard JSON on disk · NOT T36–T37 7d acceptance"
        if mode == "staging"
        else "LOCAL PREVIEW · /metrics or SSOT baseline · NOT staging T36–T37 acceptance"
    )
    draw.text((16, h - 26), footer, fill="#ffa657" if mode == "staging" else "#e3b341", font=small_font)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG", optimize=True)


def render_mod_preview(step: dict, dest: Path) -> None:
    w, h = 900, 560
    img = Image.new("RGB", (w, h), "#0d1117")
    draw = ImageDraw.Draw(img)
    title_font = _font(24, bold=True)
    sub_font = _font(16)
    mono_font = _font(14)
    small_font = _font(12)

    draw.rectangle([0, 0, w, 56], fill="#161b22", outline="#30363d")
    draw.text((16, 16), f"Mod 试点 · 步骤 {step['step']}", fill="#d2a8ff", font=title_font)

    cx, cy = w // 2, h // 2 - 10
    draw.ellipse([cx - 44, cy - 44, cx + 44, cy + 44], fill="#21262d", outline="#8957e5", width=2)
    draw.text((cx - 10, cy - 16), str(step["step"]), fill="#d2a8ff", font=_font(32, bold=True))

    draw.text((w // 2 - 180, cy + 64), step["title"], fill="#c9d1d9", font=sub_font)
    draw.text((w // 2 - 120, cy + 96), step["action"], fill="#8b949e", font=mono_font)

    draw.rectangle([40, 140, w - 40, h - 48], outline="#30363d", width=1)
    draw.text((56, 156), "Runbook checkpoint (not merchant screenshot)", fill="#484f58", font=mono_font)
    draw.text((56, 184), f"Evidence file: {step['file']}", fill="#58a6ff", font=mono_font)
    draw.text(
        (56, 212),
        "bash MODstore/scripts/mod-pilot-checklist.sh --verify after real flow",
        fill="#484f58",
        font=small_font,
    )

    draw.rectangle([0, h - 36, w, h], fill="#0b0c0e")
    draw.text(
        (16, h - 26),
        "PILOT PATH PREVIEW · awaiting real merchant flow · do NOT claim Mod store live",
        fill="#d2a8ff",
        font=small_font,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG", optimize=True)


def file_status(path: Path) -> dict:
    if path.is_file() and path.stat().st_size > 0:
        return {"present": True, "bytes": path.stat().st_size, "path": str(path.relative_to(ROOT))}
    return {"present": False, "bytes": 0, "path": str(path.relative_to(ROOT))}


def build_manifest(local_pngs: list[dict], staging_pngs: list[dict], mod_pngs: list[dict]) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    local_ok = sum(1 for p in local_pngs if p["present"])
    staging_ok = sum(1 for p in staging_pngs if p["present"])
    mod_ok = sum(1 for p in mod_pngs if p["present"])
    staging_scaffold = sum(1 for p in staging_pngs if p.get("preview") == "scaffold" and p["present"])
    mod_scaffold = sum(1 for p in mod_pngs if p.get("preview") == "path" and p["present"])
    staging_accepted = sum(1 for p in staging_pngs if p.get("preview") == "accepted" and p["present"])
    mod_verified = sum(1 for p in mod_pngs if p.get("preview") == "verified" and p["present"])

    def staging_status() -> str:
        if staging_accepted == 4:
            return "pass"
        if staging_ok == 4:
            return "partial"
        return "blocked"

    def mod_status() -> str:
        if mod_verified == 4:
            return "pass"
        if mod_ok == 4:
            return "partial"
        return "blocked"

    return {
        "generated_at": now,
        "staging_slo": {
            "label": "staging SLO 四域",
            "blocker": "T36–T37 · earliest 2026-09",
            "ready": staging_ok,
            "total": 4,
            "scaffold_ready": staging_scaffold,
            "acceptance_ready": staging_accepted,
            "status": staging_status(),
            "panels": staging_pngs,
        },
        "local_slo": {
            "label": "本地 SLO 四域预览",
            "ready": local_ok,
            "total": 4,
            "status": "pass" if local_ok == 4 else "partial",
            "panels": local_pngs,
            "note": "FastAPI /metrics 或 SSOT baseline；Grafana 真图需 local_stack_up.sh",
        },
        "mod_pilot": {
            "label": "Mod 商家试点四图",
            "blocker": "商务/环境 · mod-merchant-pilot.md",
            "ready": mod_ok,
            "total": 4,
            "path_ready": mod_scaffold,
            "verified_ready": mod_verified,
            "status": mod_status(),
            "steps": mod_pngs,
        },
        "display": {
            "staging_slo_headline": (
                f"✅ staging SLO 四图 · 4/4 · 7d 验收"
                if staging_accepted == 4
                else f"⏳ staging SLO 四图 · 脚手架 {staging_ok}/4 · 7d 验收 {staging_accepted}/4"
                if staging_ok == 4
                else f"❌ staging SLO 四图 · {staging_ok}/4"
            ),
            "mod_pilot_headline": (
                f"✅ Mod 四图 · 商家流水 4/4"
                if mod_verified == 4
                else f"⏳ Mod 四图 · 路径预览 {mod_ok}/4 · 流水 {mod_verified}/4"
                if mod_ok == 4
                else f"❌ Mod 四图 · {mod_ok}/4"
            ),
            "local_slo_headline": f"{'✅' if local_ok == 4 else '⏳'} 本地 SLO 预览 · {local_ok}/4",
        },
    }


def main() -> None:
    EVIDENCE_SLO.mkdir(parents=True, exist_ok=True)
    EVIDENCE_MOD.mkdir(parents=True, exist_ok=True)
    local_metrics = load_local_metric_values()

    local_pngs: list[dict] = []
    staging_pngs: list[dict] = []

    for panel in SLO_PANELS:
        local_name = f"grafana-local-m0-{panel['suffix']}-{DATE_SUFFIX}.png"
        staging_name = f"grafana-staging-m0-{panel['suffix']}-{DATE_SUFFIX}.png"
        local_path = EVIDENCE_SLO / local_name
        staging_path = EVIDENCE_SLO / staging_name

        render_slo_preview(panel, local_path, mode="local", metrics=local_metrics)
        render_slo_preview(panel, staging_path, mode="staging")

        preview_kind = "metrics" if _panel_stat_value(panel, local_metrics) else "scaffold"
        local_pngs.append(
            {
                **panel,
                "kind": "local",
                "filename": local_name,
                "preview": preview_kind,
                **file_status(local_path),
            }
        )
        staging_pngs.append(
            {
                **panel,
                "kind": "staging",
                "filename": staging_name,
                "preview": "scaffold",
                **file_status(staging_path),
            }
        )

    mod_pngs: list[dict] = []
    for step in MOD_STEPS:
        mod_path = EVIDENCE_MOD / step["file"]
        if mod_path.is_file() and mod_path.stat().st_size > 0:
            mod_pngs.append({**step, "preview": "path", **file_status(mod_path)})
        else:
            mod_pngs.append({**step, "preview": "missing", **file_status(mod_path)})

    manifest = build_manifest(local_pngs, staging_pngs, mod_pngs)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"[render_m0] local SLO previews: {manifest['local_slo']['ready']}/4 → {EVIDENCE_SLO}")
    print(f"[render_m0] staging SLO PNGs:   {manifest['staging_slo']['ready']}/4 (T36–T37 blocked)")
    print(f"[render_m0] Mod pilot PNGs:       {manifest['mod_pilot']['ready']}/4")
    print(f"[render_m0] manifest → {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
