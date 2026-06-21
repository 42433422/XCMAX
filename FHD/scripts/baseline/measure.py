#!/usr/bin/env python3
"""四套基线测量工具 — 数据驱动优化的度量底座。

度量四套基线(桌面端 + 手机端 + 前端):
  ① 包体积   package_size  : 桌面 .app/installer 分层构成、手机 APK/HAP、双打包浪费
  ② 启动耗时 startup       : 解析桌面 [xcagi-desktop] startup {...} 埋点;手机给出 am start -W 口径
  ③ 更新包   update_size   : 全量 zip vs 差量 blockmap,是否支持增量下载
  ④ 运行时   runtime_perf  : 前端 vue-dist 体积/分块/gzip/重资产/入口 chunk

设计原则:
  - 仅用标准库,任何机器/CI 都能跑。
  - 每项度量都是 best-effort:产物缺失记 status=missing,绝不崩。
  - 输出可提交的 JSON 快照 + 人读 Markdown,并与上次快照做 diff(数据驱动的闭环回报)。

用法:
  python3 FHD/scripts/baseline/measure.py                 # 测全部 + 写快照 + 出报告 + diff
  python3 FHD/scripts/baseline/measure.py --no-write       # 只打印,不落盘(CI 干跑)
  python3 FHD/scripts/baseline/measure.py --only runtime_perf
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import gzip
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 路径锚点。脚本位于 FHD/scripts/baseline/measure.py。
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).resolve()
FHD_ROOT = SCRIPT.parents[2]          # .../XCMAX/FHD
REPO_ROOT = SCRIPT.parents[3]         # .../XCMAX
OUT_DIR = FHD_ROOT / "baselines"
SNAP_DIR = OUT_DIR / "snapshots"

MB = 1024 * 1024


def human(n: int | None) -> str:
    if n is None:
        return "—"
    if n < 1024:
        return f"{n} B"
    for unit, div in (("GB", 1024 ** 3), ("MB", MB), ("KB", 1024)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def du_bytes(path: Path) -> int | None:
    """目录/文件实际占用字节。优先用 du(快且准),回退 Python 遍历。"""
    if not path.exists():
        return None
    try:
        out = subprocess.run(
            ["du", "-sk", str(path)], capture_output=True, text=True, timeout=120
        )
        if out.returncode == 0:
            kb = int(out.stdout.split()[0])
            return kb * 1024
    except Exception:
        pass
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


def first_glob(*patterns: str) -> Path | None:
    for pat in patterns:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return Path(hits[0])
    return None


def git_context() -> dict[str, str]:
    def _q(args: list[str]) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except Exception:
            return ""
    return {"branch": _q(["rev-parse", "--abbrev-ref", "HEAD"]), "commit": _q(["rev-parse", "--short", "HEAD"])}


# ===========================================================================
# ① 包体积
# ===========================================================================
def measure_package_size() -> dict[str, Any]:
    result: dict[str, Any] = {"desktop": _desktop_package(), "mobile": _mobile_package()}
    return result


def _desktop_package() -> dict[str, Any]:
    app = first_glob(
        str(FHD_ROOT / "release" / "**" / "*.app"),
        str(FHD_ROOT / "dist" / "**" / "*.app"),
    )
    if not app:
        return {"status": "missing", "hint": "先构建桌面包:cd FHD/desktop && npm run pack(或 build-installer.ps1)"}

    res = app / "Contents" / "Resources"
    frameworks = app / "Contents" / "Frameworks"
    backend = res / "backend"
    embedded_fe = backend / "_internal" / "templates" / "vue-dist"
    extra_fe = res / "frontend"

    components = []
    for name, p in [
        ("Electron Frameworks(Chromium 运行时,基本固定)", frameworks),
        ("Python 后端(PyInstaller 冻结)", backend),
        ("前端 frontend(extraResource)", extra_fe),
        ("app.asar(主进程代码)", res / "app.asar"),
    ]:
        b = du_bytes(p)
        if b is not None:
            components.append({"name": name, "bytes": b, "human": human(b)})
    components.sort(key=lambda c: c["bytes"], reverse=True)

    # 双打包检测:frontend extraResource 与后端内嵌 vue-dist 互为副本
    dup = []
    emb_b, extra_b = du_bytes(embedded_fe), du_bytes(extra_fe)
    if emb_b and extra_b:
        dup.append({
            "name": "前端 vue-dist 被打包两次(后端内嵌 + frontend extraResource)",
            "embedded_bytes": emb_b, "extra_bytes": extra_b,
            "removable_bytes": extra_b, "removable_human": human(extra_b),
            "note": "serve 路径是后端内嵌副本(loadURL→FastAPI);frontend extraResource 仅 cache-hash fallback,可去",
        })

    # 后端大件 top（瘦身候选）
    top_libs = []
    internal = backend / "_internal"
    if internal.is_dir():
        for child in internal.iterdir():
            b = du_bytes(child)
            if b and b >= 3 * MB:
                top_libs.append({"name": child.name, "bytes": b, "human": human(b)})
        top_libs.sort(key=lambda c: c["bytes"], reverse=True)

    # 已知可摘果子(本工具会随 spec 更新自动反映)
    removable_now = []
    mypy_b = du_bytes(internal / "mypy")
    if mypy_b:
        removable_now.append({"name": "mypy(冻结包死代码,运行时零 import)", "bytes": mypy_b, "human": human(mypy_b)})
    if extra_b:
        removable_now.append({"name": "frontend 重复打包", "bytes": extra_b, "human": human(extra_b)})

    total = du_bytes(app) or 0
    removable_total = sum(r["bytes"] for r in removable_now)
    return {
        "status": "ok",
        "app_path": str(app.relative_to(REPO_ROOT)),
        "total_bytes": total, "total_human": human(total),
        "components": components,
        "duplication": dup,
        "top_backend_libs": top_libs[:15],
        "removable_now": removable_now,
        "removable_now_bytes": removable_total,
        "projected_after_p0_quickwins_bytes": max(0, total - removable_total),
        "projected_after_p0_quickwins_human": human(max(0, total - removable_total)),
    }


def _mobile_package() -> dict[str, Any]:
    apk = first_glob(
        str(REPO_ROOT / "release" / "**" / "*Android*.apk"),
        str(FHD_ROOT / "mobile-android" / "artifacts" / "*release*.apk"),
        str(REPO_ROOT / "release" / "**" / "*.apk"),
    )
    hap = first_glob(str(REPO_ROOT / "release" / "**" / "*.hap"))
    out: dict[str, Any] = {}
    if not apk and not hap:
        return {"status": "missing", "hint": "先构建手机包:FHD/mobile-android gradlew assembleEnterpriseRelease"}
    if apk:
        b = apk.stat().st_size
        out["android_apk"] = {"path": str(apk.relative_to(REPO_ROOT)), "bytes": b, "human": human(b),
                              "breakdown": _apk_breakdown(apk)}
    if hap:
        b = hap.stat().st_size
        out["harmony_hap"] = {"path": str(hap.relative_to(REPO_ROOT)), "bytes": b, "human": human(b)}
    out["status"] = "ok"
    return out


def _apk_breakdown(apk: Path) -> list[dict[str, Any]]:
    """APK 是 zip;按顶层目录聚合压缩后大小(dex/lib/res/assets)。"""
    import zipfile
    buckets: dict[str, int] = {}
    try:
        with zipfile.ZipFile(apk) as z:
            for info in z.infolist():
                top = info.filename.split("/")[0]
                key = top if (top.endswith(".dex") or top in {"lib", "res", "assets", "META-INF", "kotlin", "resources.arsc", "AndroidManifest.xml"}) else "other"
                if info.filename.endswith(".dex"):
                    key = "dex"
                buckets[key] = buckets.get(key, 0) + info.compress_size
    except Exception as exc:  # noqa: BLE001
        return [{"name": "breakdown_unavailable", "error": str(exc)}]
    items = [{"name": k, "bytes": v, "human": human(v)} for k, v in buckets.items()]
    items.sort(key=lambda c: c["bytes"], reverse=True)
    return items


# ===========================================================================
# ② 启动耗时
# ===========================================================================
def measure_startup() -> dict[str, Any]:
    """解析桌面 [xcagi-desktop] startup {...} JSON 埋点(main.ts 已有)。"""
    marker = "[xcagi-desktop] startup"
    log_globs = [
        str(FHD_ROOT / ".xcmax-logs" / "**" / "*.log"),
        str(REPO_ROOT / ".xcmax-logs" / "**" / "*.log"),
        str(FHD_ROOT / "**" / "backend*.log"),
    ]
    latest: dict[str, Any] | None = None
    scanned = 0
    for pat in log_globs:
        for path in glob.glob(pat, recursive=True):
            scanned += 1
            try:
                text = Path(path).read_text(errors="ignore")
            except OSError:
                continue
            idx = text.rfind(marker)
            if idx == -1:
                continue
            tail = text[idx + len(marker):]
            brace = tail.find("{")
            if brace == -1:
                continue
            depth, end = 0, -1
            for i, ch in enumerate(tail[brace:], start=brace):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end == -1:
                continue
            try:
                latest = {"source": str(Path(path).relative_to(REPO_ROOT)), "marks": json.loads(tail[brace:end])}
            except json.JSONDecodeError:
                continue
    desktop: dict[str, Any]
    if latest:
        m = latest["marks"]
        desktop = {
            "status": "ok", "source": latest["source"], "marks": m,
            "note": "marks 含 backendSpawnMs/tcp5000Ms/desktopStatusMs:首屏当前阻塞在后端健康检查(tcp5000Ms),即'分钟级'根因",
        }
    else:
        desktop = {
            "status": "no_run_captured", "logs_scanned": scanned,
            "hint": "从终端启动一次桌面 app 复现埋点:cd FHD/desktop && npm run dev,关注 stdout 的 [xcagi-desktop] startup {...}",
        }
    mobile = {
        "status": "needs_device",
        "android_cold_start": "adb shell am start -W -n com.xiuci.xcagi.mobile/.MainActivity | grep TotalTime",
        "note": "需真机/模拟器;TotalTime(ms)为冷启口径",
    }
    return {"desktop": desktop, "mobile": mobile}


# ===========================================================================
# ③ 更新包(全量 vs 差量)
# ===========================================================================
def measure_update_size() -> dict[str, Any]:
    rel = FHD_ROOT / "release"
    zips = sorted(glob.glob(str(rel / "**" / "*-mac-*.zip"), recursive=True)
                  + glob.glob(str(rel / "**" / "*Setup*.exe"), recursive=True))
    if not zips:
        return {"status": "missing", "hint": "先构建桌面包,产物含 *.zip/*.exe + *.blockmap"}
    artifacts = []
    seen_names: set[str] = set()  # 同一产物可能出现在多个 release 子目录,按文件名去重
    for zp in zips:
        p = Path(zp)
        if p.name in seen_names:
            continue
        seen_names.add(p.name)
        bm = Path(str(p) + ".blockmap")
        full = p.stat().st_size
        artifacts.append({
            "file": p.name,
            "full_bytes": full, "full_human": human(full),
            "blockmap_present": bm.exists(),
            "blockmap_bytes": bm.stat().st_size if bm.exists() else None,
            "differential_supported": bm.exists(),
        })
    any_bm = any(a["blockmap_present"] for a in artifacts)
    return {
        "status": "ok",
        "artifacts": artifacts,
        "differential_ready": any_bm,
        "note": ("blockmap 已生成 → electron-updater 在生成版 provider 下会自动只下增量块;"
                 "下一步应实测一次跨版本更新的真实下载字节(本工具暂以全量为基线)。"
                 if any_bm else "未发现 blockmap,当前只能全量更新。"),
        "measured_differential_bytes": None,  # 待跨版本实测填入
    }


# ===========================================================================
# ④ 运行时性能(前端 bundle)
# ===========================================================================
def measure_runtime_perf() -> dict[str, Any]:
    dist = FHD_ROOT / "templates" / "vue-dist"
    if not dist.is_dir():
        return {"frontend_bundle": {"status": "missing", "hint": "先构建前端:cd FHD/frontend && npm run build"}}

    js_dir = dist / "assets" / "js"
    css_dir = dist / "assets" / "css"

    def _sum_dir(d: Path, exts: tuple[str, ...]) -> tuple[int, int, list[dict[str, Any]]]:
        raw = gz = 0
        items: list[dict[str, Any]] = []
        if not d.is_dir():
            return 0, 0, items
        for f in d.iterdir():
            if not f.is_file() or f.suffix not in exts:
                continue
            r = f.stat().st_size
            try:
                g = len(gzip.compress(f.read_bytes(), 6))
            except Exception:
                g = 0
            raw += r
            gz += g
            items.append({"name": f.name, "bytes": r, "gzip_bytes": g, "human": human(r), "gzip_human": human(g)})
        items.sort(key=lambda c: c["bytes"], reverse=True)
        return raw, gz, items

    js_raw, js_gz, js_items = _sum_dir(js_dir, (".js",))
    css_raw, css_gz, css_items = _sum_dir(css_dir, (".css",))

    # 入口 chunk(启动关键路径)
    entry = next((c for c in js_items if c["name"].startswith("index-")), None)

    # 重资产(应进 P1「按需下载」桶,不该进基础包/启动路径)
    heavy = []
    for label, patterns in [
        ("ONNX Runtime WASM(离线 TTS)", ["**/*ort-wasm*"]),
        ("yuangong 数据/fixtures", ["yuangong/**"]),
    ]:
        b = 0
        seen: set[Path] = set()  # 去重:多个 glob 可能命中同一文件
        for pat in patterns:
            for hit in glob.glob(str(dist / pat), recursive=True):
                hp = Path(hit).resolve()
                if hp.is_file() and hp not in seen:
                    seen.add(hp)
                    b += hp.stat().st_size
        if b:
            heavy.append({"name": label, "bytes": b, "human": human(b)})
    for c in js_items[:6]:
        if any(tok in c["name"] for tok in ("transformers", "xlsx", "echarts", "mermaid")):
            heavy.append({"name": f"懒加载大块 {c['name']}(随包发布但多数用户不触发)", "bytes": c["bytes"], "human": human(c["bytes"])})

    total = du_bytes(dist) or 0
    return {
        "frontend_bundle": {
            "status": "ok",
            "dist_path": str(dist.relative_to(REPO_ROOT)),
            "total_bytes": total, "total_human": human(total),
            "js_total_bytes": js_raw, "js_total_human": human(js_raw), "js_gzip_human": human(js_gz),
            "css_total_bytes": css_raw, "css_total_human": human(css_raw), "css_gzip_human": human(css_gz),
            "chunk_count": len(js_items),
            "entry_chunk": entry,
            "top_chunks": js_items[:8],
            "heavy_on_demand_candidates": heavy,
            "manual_chunks": False,
            "note": "vite/build.js 无 manualChunks;入口 chunk + 重资产是 P1 抓手。",
        }
    }


# ===========================================================================
# 编排 / 报告 / diff
# ===========================================================================
MEASURERS = {
    "package_size": measure_package_size,
    "startup": measure_startup,
    "update_size": measure_update_size,
    "runtime_perf": measure_runtime_perf,
}


def _headline(snap: dict[str, Any]) -> dict[str, int | None]:
    b = snap["baselines"]
    pkg = b.get("package_size", {})
    return {
        "desktop_app_bytes": pkg.get("desktop", {}).get("total_bytes"),
        "desktop_removable_now_bytes": pkg.get("desktop", {}).get("removable_now_bytes"),
        "mobile_apk_bytes": pkg.get("mobile", {}).get("android_apk", {}).get("bytes"),
        "frontend_dist_bytes": b.get("runtime_perf", {}).get("frontend_bundle", {}).get("total_bytes"),
        "frontend_js_gzip": None,
    }


def _delta(cur: int | None, prev: int | None) -> str:
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if d == 0:
        return "  (±0)"
    sign = "▲" if d > 0 else "▼"
    return f"  ({sign}{human(abs(d))})"


def render_markdown(snap: dict[str, Any], prev: dict[str, Any] | None) -> str:
    L: list[str] = []
    L.append("# 四套基线 — 真实测量报告\n")
    L.append(f"- 采集时间(UTC):`{snap['captured_at']}`")
    L.append(f"- Git:`{snap['git']['branch']}@{snap['git']['commit']}`  ·  平台:`{snap['host']['platform']}/{snap['host']['arch']}`")
    L.append("- 由 `FHD/scripts/baseline/measure.py` 自动生成;数字均来自真实产物,非估算。\n")

    cur_h = _headline(snap)
    prev_h = _headline(prev) if prev else {}
    L.append("## 速览(对比上次快照)\n")
    L.append("| 指标 | 当前 | 环比 |")
    L.append("|---|---:|---|")
    L.append(f"| 桌面 .app 体积 | {human(cur_h['desktop_app_bytes'])} |{_delta(cur_h['desktop_app_bytes'], prev_h.get('desktop_app_bytes'))} |")
    L.append(f"| 桌面可立即削减(P0) | {human(cur_h['desktop_removable_now_bytes'])} | — |")
    L.append(f"| 手机 APK 体积 | {human(cur_h['mobile_apk_bytes'])} |{_delta(cur_h['mobile_apk_bytes'], prev_h.get('mobile_apk_bytes'))} |")
    L.append(f"| 前端 vue-dist 体积 | {human(cur_h['frontend_dist_bytes'])} |{_delta(cur_h['frontend_dist_bytes'], prev_h.get('frontend_dist_bytes'))} |")
    L.append("")

    b = snap["baselines"]

    # ① 包体积
    d = b.get("package_size", {}).get("desktop", {})
    L.append("## ① 包体积基线 — 桌面\n")
    if d.get("status") == "ok":
        L.append(f"**{d['app_path']}** = **{d['total_human']}**\n")
        L.append("| 构成 | 体积 |")
        L.append("|---|---:|")
        for c in d["components"]:
            L.append(f"| {c['name']} | {c['human']} |")
        L.append("")
        if d.get("duplication"):
            L.append("**双打包浪费:**")
            for dup in d["duplication"]:
                L.append(f"- {dup['name']} → 可去 **{dup['removable_human']}**({dup['note']})")
            L.append("")
        if d.get("removable_now"):
            L.append(f"**P0 可立即削减合计 {human(d['removable_now_bytes'])} → 预计降到 {d['projected_after_p0_quickwins_human']}:**")
            for r in d["removable_now"]:
                L.append(f"- {r['name']}:{r['human']}")
            L.append("")
        if d.get("top_backend_libs"):
            L.append("**后端大件(P1/P2 瘦身候选):** " + ", ".join(f"{c['name']} {c['human']}" for c in d["top_backend_libs"][:10]))
            L.append("")
    else:
        L.append(f"_产物缺失:{d.get('hint','')}_\n")

    m = b.get("package_size", {}).get("mobile", {})
    L.append("## ① 包体积基线 — 手机\n")
    if m.get("status") == "ok":
        if "android_apk" in m:
            a = m["android_apk"]
            L.append(f"**Android APK** `{a['path']}` = **{a['human']}**")
            if a.get("breakdown"):
                L.append("  · " + ", ".join(f"{x['name']} {x['human']}" for x in a["breakdown"] if "human" in x))
        if "harmony_hap" in m:
            L.append(f"\n**Harmony HAP** = {m['harmony_hap']['human']}")
        L.append("")
    else:
        L.append(f"_产物缺失:{m.get('hint','')}_\n")

    # ② 启动
    s = b.get("startup", {})
    L.append("## ② 启动耗时基线\n")
    sd = s.get("desktop", {})
    if sd.get("status") == "ok":
        L.append(f"桌面(来源 `{sd['source']}`):`{json.dumps(sd['marks'], ensure_ascii=False)}`")
        L.append(f"> {sd['note']}")
    else:
        L.append(f"桌面:_{sd.get('status')}_ — {sd.get('hint','')}")
    L.append(f"\n手机:{s.get('mobile', {}).get('android_cold_start','')}")
    L.append("")

    # ③ 更新包
    u = b.get("update_size", {})
    L.append("## ③ 更新包基线(全量 vs 差量)\n")
    if u.get("status") == "ok":
        L.append("| 产物 | 全量 | blockmap | 支持增量 |")
        L.append("|---|---:|---:|:--:|")
        for a in u["artifacts"]:
            L.append(f"| {a['file']} | {a['full_human']} | {human(a['blockmap_bytes'])} | {'✅' if a['differential_supported'] else '❌'} |")
        L.append(f"\n> {u['note']}")
    else:
        L.append(f"_产物缺失:{u.get('hint','')}_")
    L.append("")

    # ④ 运行时
    fb = b.get("runtime_perf", {}).get("frontend_bundle", {})
    L.append("## ④ 运行时性能基线 — 前端 bundle\n")
    if fb.get("status") == "ok":
        L.append(f"**{fb['dist_path']}** 总 **{fb['total_human']}** · JS {fb['js_total_human']}(gzip {fb['js_gzip_human']}) · CSS {fb['css_total_human']}(gzip {fb['css_gzip_human']}) · {fb['chunk_count']} 个 JS chunk")
        if fb.get("entry_chunk"):
            e = fb["entry_chunk"]
            L.append(f"\n入口 chunk(启动关键路径):`{e['name']}` {e['human']}(gzip {e['gzip_human']})")
        L.append("\n**最大 chunk:**")
        for c in fb["top_chunks"][:6]:
            L.append(f"- {c['name']}:{c['human']}(gzip {c['gzip_human']})")
        if fb.get("heavy_on_demand_candidates"):
            L.append("\n**重资产(P1 应改按需下载,不进基础包/启动路径):**")
            for h in fb["heavy_on_demand_candidates"]:
                L.append(f"- {h['name']}:{h['human']}")
        L.append(f"\n> {fb['note']}")
    else:
        L.append(f"_产物缺失:{fb.get('hint','')}_")
    L.append("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="四套基线测量")
    ap.add_argument("--only", choices=list(MEASURERS), help="只测某一套")
    ap.add_argument("--no-write", action="store_true", help="只打印,不落盘")
    args = ap.parse_args()

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    chosen = {args.only: MEASURERS[args.only]} if args.only else MEASURERS
    baselines = {name: fn() for name, fn in chosen.items()}
    snap = {
        "schema_version": 1,
        "captured_at": now,
        "git": git_context(),
        "host": {"platform": sys.platform, "arch": os.uname().machine if hasattr(os, "uname") else "unknown"},
        "baselines": baselines,
    }

    prev = None
    latest_json = OUT_DIR / "latest.json"
    if latest_json.exists():
        try:
            prev = json.loads(latest_json.read_text())
        except Exception:
            prev = None

    md = render_markdown(snap, prev) if not args.only else json.dumps(snap, ensure_ascii=False, indent=2)
    print(md)

    if not args.no_write:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = now.replace(":", "").replace("-", "")
        (SNAP_DIR / f"{stamp}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=2))
        latest_json.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
        if not args.only:
            (OUT_DIR / "latest.md").write_text(md)
        print(f"\n[written] {SNAP_DIR / (stamp + '.json')}")
        print(f"[written] {latest_json}")
        if not args.only:
            print(f"[written] {OUT_DIR / 'latest.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
