#!/usr/bin/env python3
"""产品能力中心生成器。

核心原则：No Evidence, No Claim。
- 能力目录 SSOT：data/capabilities/catalog.json
- 生成器逐项校验证据（实现路径 / 自动化测试 / CI 工作流 / 运行证据 / 文档），
  证据不满足声明状态时自动降级并记录原因，严禁伪造功能状态。
- 全部公开数字（能力总数、已验证数量、最近验证时间等）由目录自动统计。

用法：
  python3 scripts/build_capability_center.py            # 生成页面 + 数据
  python3 scripts/build_capability_center.py --check    # CI 漂移门禁：目录与已提交页面不一致则失败
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

WEBSITE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = WEBSITE_DIR / "data" / "capabilities" / "catalog.json"
OUT_DIR = WEBSITE_DIR / "capabilities"
PUBLIC_DATA_PATH = WEBSITE_DIR / "data" / "capabilities.json"
EVIDENCE_ASSET_DIR = OUT_DIR / "assets" / "evidence"

STATUS_META = {
    "verified": {"label": "已验证", "cls": "st-verified", "rank": 3},
    "partial": {"label": "部分验证", "cls": "st-partial", "rank": 2},
    "implemented": {"label": "已实现待验证", "cls": "st-implemented", "rank": 1},
    "planned": {"label": "规划中", "cls": "st-planned", "rank": 0},
}
STATUS_ORDER = ["verified", "partial", "implemented", "planned"]

# 矩阵图例：状态 → 一句话口径，与状态分级说明同源，避免两处口径漂移。
STATUS_LEGEND = (
    ("verified", "有实现、自动化测试与 CI 门禁记录，公开页面可逐项查证"),
    ("partial", "实现已合入且有部分证据，验证覆盖不完整，限制已知"),
    ("implemented", "代码已合入，暂缺自动化测试或实机验证证据"),
    ("planned", "仅有设计与规划，无已合入实现"),
)

PLATFORM_META = {
    "windows": "Windows 桌面",
    "macos": "macOS 桌面",
    "web": "Web",
    "android": "Android",
    "ios": "iOS",
}

# 完成度加权口径：公开进度数字的唯一算法，页面同时展示该规则，不接受人工填写。
COMPLETION_WEIGHT = {"verified": 1.0, "partial": 0.7, "implemented": 0.4, "planned": 0.0}

# 状态 → 矩阵勾选图标（已完成 / 部分完成 / 进行中 / 未开始）。
TICK_CLASS = {
    "verified": "t-ok",
    "partial": "t-part",
    "implemented": "t-wip",
    "planned": "t-todo",
}

# 域卡强调色：按目录顺序循环，仅用于视觉分区，不表达任何状态。
DOMAIN_ACCENTS = (
    "#2f6df6", "#7c4dff", "#12a150", "#ff8a00", "#e6486b",
    "#0f9d8c", "#e5484d", "#2f6df6", "#7c4dff", "#12a150",
)

# 三端产品形态：等级文案取自 FHD/VERSION.md「各端交付等级」表，不另写对外口径。
PRODUCT_FORMS = (
    {"name": "桌面端", "sub": "Windows / macOS", "keys": ("Windows 桌面", "macOS 桌面")},
    {"name": "移动端", "sub": "Android", "keys": ("Android",)},
    {"name": "管理端", "sub": "Web", "keys": ("Web / 后端",)},
)


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def e(path: str) -> Path:
    return REPO_ROOT / path


def path_exists(rel: str) -> bool:
    return e(rel).exists()


def git(*args: str, cwd: Path = REPO_ROOT) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, timeout=30, check=True,
            encoding="utf-8", errors="replace",  # 显式 UTF-8，消除 CI/locale 差异
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def last_commit(paths: list[str], fmt: str = "%cI") -> str | None:
    real = [p for p in paths if p and path_exists(p)]
    if not real:
        return None
    out = git("log", "-1", f"--format={fmt}", "--", *real)
    return out or None


# ---------------------------------------------------------------- validation

def validate_feature(feat: dict, warnings: list[str]) -> dict:
    """校验单个功能的证据，返回最终状态与证据明细。No Evidence, No Claim。"""
    ev = feat.get("evidence", {}) or {}
    impl = ev.get("impl", []) or []
    tests = ev.get("tests", []) or []
    ci = ev.get("ci", []) or []
    docs = ev.get("docs", []) or []
    shots = ev.get("screenshots", []) or []
    videos = ev.get("videos", []) or []

    impl_ok = [p for p in impl if path_exists(p)]
    impl_missing = [p for p in impl if not path_exists(p)]
    tests_ok = [p for p in tests if path_exists(p)]
    ci_ok = [p for p in ci if path_exists(p.split(":")[0])]
    docs_ok = [p for p in docs if path_exists(p)]
    shots_ok = [p for p in shots if path_exists(p)]
    videos_ok = [p for p in videos if path_exists(p)]

    for p in impl_missing:
        warnings.append(f"[{feat['id']}] 实现路径不存在: {p}")
    for p in tests:
        if p not in tests_ok:
            warnings.append(f"[{feat['id']}] 测试路径不存在: {p}")
    for p in shots:
        if p not in shots_ok:
            warnings.append(f"[{feat['id']}] 运行证据不存在: {p}")
    for p in videos:
        if p not in videos_ok:
            warnings.append(f"[{feat['id']}] 运行录像不存在: {p}")

    claimed = feat["status"]
    final = claimed
    reasons: list[str] = []

    def downgrade(to: str, reason: str) -> None:
        nonlocal final
        if STATUS_META[to]["rank"] < STATUS_META[final]["rank"]:
            final = to
            reasons.append(reason)

    if claimed == "verified":
        if not impl_ok:
            downgrade("partial", "缺少可验证的实现路径")
        if not tests_ok:
            downgrade("partial", "缺少自动化测试证据")
        if not ci_ok:
            downgrade("partial", "缺少 CI 门禁记录")
    elif claimed == "partial":
        if not impl_ok:
            downgrade("implemented", "实现路径缺失或未合入")
        elif not tests_ok and not shots_ok and not videos_ok:
            downgrade("implemented", "既无自动化测试也无运行证据")
    elif claimed == "implemented":
        if not impl_ok:
            downgrade("planned", "无任何已合入实现")
    elif claimed == "planned":
        if impl_ok:
            warnings.append(f"[{feat['id']}] 声明为规划中但存在实现路径（仅警告，不自动升级）: {impl_ok[0]}")

    # 「最近验证时间」只取能力自身拥有、且只会因该能力而变更的证据（实现 + 测试）。
    # CI 工作流是跨能力共享的基础设施：任何一次无关的 workflow 编辑都会顶起全部 30 项
    # 引用它的能力的验证时间，使已提交页面看似漂移（SSOT Drift Gate 反复误报）。
    # CI 记录仍然是 "verified" 状态的必需证据（见上方降级判断），只是不参与时间戳。
    ev_paths_for_time = impl_ok + tests_ok
    verified_at = last_commit(ev_paths_for_time)

    commit_info = []
    for c in ev.get("commits", []) or []:
        commit_info.append({"sha": c.get("sha", ""), "subject": c.get("subject", ""), "date": c.get("date", "")})
    if not commit_info and impl_ok:
        raw = last_commit([impl_ok[0]], fmt="%h%x1f%cI%x1f%s")
        if raw:
            sha, date, subject = raw.split("\x1f")
            commit_info.append({"sha": sha, "subject": subject, "date": date[:10]})

    return {
        **feat,
        "status": final,
        "claimed_status": claimed,
        "downgraded": final != claimed,
        "downgrade_reasons": reasons,
        "evidence": {
            "impl": impl_ok,
            "api": ev.get("api", []) or [],
            "tests": tests_ok,
            "ci": ci_ok,
            "docs": docs_ok,
            "screenshots": shots_ok,
            "videos": videos_ok,
            "commits": commit_info,
        },
        "verified_at": verified_at[:10] if verified_at else None,
    }


def load_platform_levels() -> dict[str, str]:
    """从 FHD/VERSION.md「各端交付等级」表自动读取对外口径。"""
    levels: dict[str, str] = {}
    source = REPO_ROOT / "FHD" / "VERSION.md"
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return levels
    in_section = False
    for line in text.splitlines():
        if "各端交付等级" in line:
            in_section = True
            continue
        if in_section and line.strip().startswith("|"):
            cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
            # cells[0].strip("-: ") 为空即分隔行（`----` / `:---:` 等），不按固定字符串枚举。
            if len(cells) >= 3 and cells[0] not in ("端",) and cells[0].strip("-: ") and "：" not in cells[0]:
                levels[cells[0]] = cells[1]
        elif in_section and line.strip() and not line.strip().startswith("|"):
            break
    return levels


def load_product_version() -> str:
    """从 FHD/VERSION.md 读取稳定产品版本，官网不写死版本号。"""
    try:
        text = (REPO_ROOT / "FHD" / "VERSION.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"XCAGI 稳定产品版本\*\*\s*\|\s*`([^`]+)`", text)
    return m.group(1) if m else ""


def completion(features: list[dict]) -> int:
    """按 COMPLETION_WEIGHT 加权计算一组能力的完成度百分比（四舍五入）。"""
    if not features:
        return 0
    weighted = sum(COMPLETION_WEIGHT.get(f["status"], 0.0) for f in features)
    return int(round(weighted / len(features) * 100))


def build(repo_root_note: bool = True) -> tuple[dict, list[str], list[dict]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    warnings: list[str] = []
    domains_out: list[dict] = []
    feature_index: list[dict] = []

    for dom in catalog["domains"]:
        modules_out = []
        for mod in dom["modules"]:
            feats_out = []
            for feat in mod["features"]:
                enriched = validate_feature(feat, warnings)
                feats_out.append(enriched)
                feature_index.append(
                    {
                        "id": enriched["id"],
                        "name": enriched["name"],
                        "status": enriched["status"],
                        "domain_id": dom["id"],
                        "domain_name": dom["name"],
                        "module_id": mod["id"],
                        "module_name": mod["name"],
                        "platforms": enriched.get("platforms", []),
                        "summary": enriched.get("summary", ""),
                    }
                )
            modules_out.append({**mod, "features": feats_out})
        domains_out.append({**dom, "modules": modules_out})

    stats = compute_stats(domains_out, feature_index)
    data = {
        "schema_version": 1,
        "catalog_version": catalog.get("catalog_version", ""),
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "principle": "No Evidence, No Claim：所有状态由构建脚本按仓库证据校验，证据缺失自动降级。",
        "stats": stats,
        "product_version": load_product_version(),
        "platform_levels": load_platform_levels(),
        "deployment_modes": catalog.get("deployment_modes", []) or [],
        "next_plan": catalog.get("next_plan", []) or [],
        "domains": [
            {
                "id": d["id"],
                "name": d["name"],
                "description": d.get("description", ""),
                "modules": [
                    {
                        "id": m["id"],
                        "name": m["name"],
                        "features": [
                            {
                                "id": f["id"],
                                "name": f["name"],
                                "status": f["status"],
                                "platforms": f.get("platforms", []),
                                "summary": f.get("summary", ""),
                            }
                            for f in m["features"]
                        ],
                    }
                    for m in d["modules"]
                ],
            }
            for d in domains_out
        ],
    }
    return data, warnings, domains_out


def compute_stats(domains_out: list[dict], feature_index: list[dict]) -> dict:
    by_status = {s: 0 for s in STATUS_ORDER}
    for f in feature_index:
        by_status[f["status"]] += 1
    verified_times = []
    for d in domains_out:
        for m in d["modules"]:
            for f in m["features"]:
                if f["status"] == "verified" and f.get("verified_at"):
                    verified_times.append(f["verified_at"])
    platform_counts: dict[str, int] = {}
    for f in feature_index:
        for p in f["platforms"]:
            platform_counts[p] = platform_counts.get(p, 0) + 1
    return {
        "total": len(feature_index),
        "by_status": by_status,
        "domains": len(domains_out),
        "modules": sum(len(d["modules"]) for d in domains_out),
        "verified_total": by_status["verified"],
        "last_verified_at": max(verified_times) if verified_times else None,
        "platform_counts": platform_counts,
        "completion": completion(feature_index),
    }


# ---------------------------------------------------------------- rendering

def css(href: str) -> str:
    return f'<link rel="stylesheet" href="{href}?v=20260919a" />'


def header_html(page_key: str, title_suffix: str, description: str, canonical: str) -> str:
    # 生成物横幅：明确声明页面由脚本生成，避免被当成手工维护页面直接编辑。
    return f"""<!doctype html>
<!-- 此文件由 scripts/build_capability_center.py 自动生成，请勿手改（DO NOT EDIT）。 -->
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{esc(title_suffix)} | 成都修茈科技有限公司</title>
    <meta name="description" content="{esc(description)}" />
    <link rel="canonical" href="{esc(canonical)}" />
    <link rel="stylesheet" href="/styles.css?v=20260722h" />
    {css("/capabilities/assets/capabilities.css")}
  </head>
<body data-page="{esc(page_key)}">
<header class="site-header">
  <div class="container header-inner">
    <a class="brand-mark" href="/index.html">
      <span class="brand-seal"><img src="/assets/xiu-ci-logo.png" alt="修茈科技 Logo" /></span>
      <span class="brand-name"><strong>成都修茈科技有限公司</strong><span>XCAGI Automation</span></span>
    </a>
    <nav class="nav" aria-label="站点导航">
      <div class="nav-menu">
        <a data-nav="index" href="/index.html">首页</a>
        <a data-nav="about" href="/about.html">关于修茈</a>
        <a data-nav="visualization" href="/visualization">可视化展示</a>
        <a data-nav="solutions" href="/solutions.html">方案与案例</a>
        <a class="nav-optional" data-nav="news" href="/news.html">新闻资讯</a>
        <a class="nav-optional active" data-nav="capabilities" href="/capabilities/">产品能力</a>
        <a data-nav="contact" href="/contact.html">联系我们</a>
        <a data-nav="developer" href="/developer.html">开发者中心</a>
        <a data-nav="world-will" href="/world-will">世界意志</a>
      </div>
      <div class="nav-actions">
        <a class="nav-action nav-action--outline" href="/market/">AI 市场</a>
        <a class="nav-action nav-action--primary" href="/download">产品下载</a>
      </div>
    </nav>
    <button class="mobile-menu-toggle" id="mobile-menu-toggle" type="button" aria-controls="mobile-menu" aria-label="打开菜单" aria-expanded="false"><span></span><span></span><span></span></button>
  </div>
</header>
<div class="mobile-menu-overlay" id="mobile-menu-overlay"></div>
<nav class="mobile-menu" id="mobile-menu" aria-hidden="true" inert>
  <a href="/index.html" class="mobile-menu-link" data-nav="index">首页</a>
  <a href="/about.html" class="mobile-menu-link" data-nav="about">关于修茈</a>
  <a href="/visualization" class="mobile-menu-link" data-nav="visualization">可视化展示</a>
  <a href="/solutions.html" class="mobile-menu-link" data-nav="solutions">方案与案例</a>
  <a href="/news.html" class="mobile-menu-link" data-nav="news">新闻资讯</a>
  <a href="/capabilities/" class="mobile-menu-link active" data-nav="capabilities">产品能力</a>
  <a href="/contact.html" class="mobile-menu-link" data-nav="contact">联系我们</a>
  <a href="/developer.html" class="mobile-menu-link" data-nav="developer">开发者中心</a>
  <a href="/world-will" class="mobile-menu-link" data-nav="world-will">世界意志</a>
  <div class="mobile-menu-actions">
    <a href="/market/" class="mobile-menu-link mobile-menu-link--outline">AI 市场</a>
    <a href="/download" class="mobile-menu-link mobile-menu-link--primary">产品下载</a>
  </div>
</nav>
"""


def footer_html() -> str:
    return """<footer class="site-footer">
      <div class="container footer-inner">
        <div>
          <a class="brand-mark" href="/index.html"
            ><span class="brand-seal"
              ><img src="/assets/xiu-ci-logo.png" alt="修茈科技 Logo" /></span
            ><span class="brand-name"
              ><strong>成都修茈科技有限公司</strong><span>XCAGI Automation</span></span
            ></a
          >
          <p class="footer-copy">
            &copy; <span id="year"></span> 成都修茈科技有限公司 保留所有权利。
          </p>
          <p class="footer-meta footer-legal">
            <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer"
              >蜀ICP备2026014056号-3A</a
            >
          </p>
        </div>
        <div class="footer-links">
          <a href="/solutions.html">解决方案</a
          ><a href="/cases.html">客户案例</a><a href="/news.html">新闻资讯</a
          ><a href="/capabilities/">产品能力</a><a href="/contact.html">联系我们</a>
        </div>
      </div>
    </footer>
<button id="back-to-top" class="back-to-top" aria-label="回到顶部"></button>
<script src="/main.js?v=20260722h"></script>
</body>
</html>
"""


def status_badge(status: str) -> str:
    meta = STATUS_META[status]
    return f'<span class="cap-status {meta["cls"]}">{meta["label"]}</span>'


def platform_tags(platforms: list[str]) -> str:
    return "".join(
        f'<span class="cap-platform">{esc(PLATFORM_META.get(p, p))}</span>' for p in platforms
    )


def render_index(data: dict, domains_full: list[dict]) -> str:
    s = data["stats"]
    version = data.get("product_version") or ""
    ver_html = f' <span class="capm-ver">v{esc(version)}</span>' if version else ""
    last_verified = s["last_verified_at"] or "—"

    # 左主体：10 张域卡（5 列 × 2 行），逐条列出功能并链接到各自证据详情页。
    cards = []
    for i, d in enumerate(domains_full):
        feats = [f for m in d["modules"] for f in m["features"]]
        pct = completion(feats)
        items = "".join(
            f'<li><a class="capm-feat" href="/capabilities/feature/{esc(f["id"])}.html">'
            f'<i class="capm-tick {TICK_CLASS[f["status"]]}" aria-hidden="true"></i>'
            f"<span>{esc(f['name'])}</span></a></li>"
            for f in feats
        )
        cards.append(
            f"""<article class="capm-card" style="--accent:{DOMAIN_ACCENTS[i % len(DOMAIN_ACCENTS)]}">
          <header class="capm-card-head"><h3>{esc(d['name'])}</h3><span class="capm-card-count">（{len(feats)}项）</span></header>
          <ul class="capm-feats">{items}</ul>
          <footer class="capm-card-foot"><div class="capm-bar" role="img" aria-label="完成度 {pct}%"><span style="width:{pct}%"></span></div><span class="capm-pct">完成度 {pct}%</span></footer>
        </article>"""
        )

    # 右侧栏：三端产品形态，等级文案取自 FHD/VERSION.md，不另写口径。
    forms = []
    for form in PRODUCT_FORMS:
        levels = [v for v in (data.get("platform_levels", {}).get(k, "") for k in form["keys"]) if v]
        level = " / ".join(levels) or "见版本说明"
        warn = any("实验" in v or "非签约" in v for v in levels)
        forms.append(
            f"""<li class="capm-form"><div><strong>{esc(form['name'])}</strong><span>{esc(form['sub'])}</span></div>
          <em class="capm-badge {'capm-badge--warn' if warn else 'capm-badge--ok'}">{esc(level)}</em></li>"""
        )

    # 右侧栏：安全与网络三模式，由目录 SSOT 维护。
    modes = "".join(
        f'<li class="capm-mode"><strong>{esc(m["name"])}</strong>'
        f"<span>{esc(m.get('network', ''))} + {esc(m.get('storage', ''))}</span>"
        f"<em>{esc(m.get('desc', ''))}</em></li>"
        for m in data.get("deployment_modes", [])
    )

    # 底部：待验收 / 待补齐清单，按状态严重度排序取前 5，逐条可点进证据页。
    pending = sorted(
        (f for d in domains_full for m in d["modules"] for f in m["features"] if f["status"] != "verified"),
        key=lambda f: STATUS_META[f["status"]]["rank"],
    )[:5]
    pending_items = "".join(
        f'<li><span class="capm-rank">{i + 1}</span>'
        f'<a href="/capabilities/feature/{esc(f["id"])}.html">{esc(f["name"])}</a>'
        f"{status_badge(f['status'])}</li>"
        for i, f in enumerate(pending)
    )

    # 底部：下一步重点计划，由目录 SSOT 维护。
    plan_items = "".join(
        f'<li><span class="capm-rank">{i + 1}</span><span>{esc(x)}</span></li>'
        for i, x in enumerate(data.get("next_plan", []))
    )

    legend = "".join(
        f'<li><i class="capm-tick {TICK_CLASS[k]}" aria-hidden="true"></i>'
        f'<strong>{STATUS_META[k]["label"]}</strong><span>{esc(desc)}</span></li>'
        for k, desc in STATUS_LEGEND
    )

    return f"""{header_html("capabilities", "产品能力中心", "XCMAX 产品能力矩阵：逐项公开实现与验证证据，点击任一功能查看实机截图或录像，所有数字由能力目录自动统计。", "/capabilities/")}
<main>
  <section class="capm-hero">
    <div class="container capm-hero-inner">
      <div class="capm-hero-main">
        <h1><span class="capm-logo">XCMAX</span> 企业 AI 员工桌面平台{ver_html}</h1>
        <p class="capm-sub">跨平台 · 三端协同 · 一站式 AI 员工工作台</p>
        <p class="capm-slogan">把 AI 员工装进每台企业电脑，让企业自己运转</p>
      </div>
      <div class="capm-hero-side">
        <p class="capm-hero-quote">让 AI 员工<br />创造真实的生产力</p>
        <ul class="capm-hero-tags"><li>更高效</li><li>更智能</li><li>更自由</li></ul>
      </div>
    </div>
  </section>

  <div class="container capm-layout">
    <div class="capm-main">
      <div class="capm-matrix">{''.join(cards)}</div>

      <div class="capm-bottom">
        <section class="capm-panel capm-panel--progress">
          <h2>当前版本进度</h2>
          <div class="capm-progress-top"><div class="capm-bar capm-bar--lg"><span style="width:{s['completion']}%"></span></div><strong>{s['completion']}%</strong></div>
          <p class="capm-panel-note">总体完成度按加权口径计算：已验证 100%、部分验证 70%、已实现待验证 40%、规划中 0%，按功能数加权。截至 {esc(last_verified)}，共 {s['total']} 项能力、{s['modules']} 个模块、{s['domains']} 个产品域。</p>
          <ul class="capm-legend">{legend}</ul>
        </section>
        <section class="capm-panel">
          <h2>主要问题与待验收项（Top 5）</h2>
          <ol class="capm-list">{pending_items}</ol>
        </section>
        <section class="capm-panel">
          <h2>下一步重点计划</h2>
          <ol class="capm-list">{plan_items}</ol>
        </section>
      </div>
    </div>

    <aside class="capm-side">
      <section class="capm-side-block">
        <h2>三端产品形态</h2>
        <ul class="capm-forms">{''.join(forms)}</ul>
        <p class="capm-panel-note">等级自动读取自产品版本说明 FHD/VERSION.md，非人工宣传口径。</p>
      </section>
      <section class="capm-side-block">
        <h2>安全与网络三模式</h2>
        <ul class="capm-modes">{modes}</ul>
      </section>
      <section class="capm-side-block capm-side-brand">
        <strong>XCMAX</strong>
        <span>AI EMPLOYEES FOR A BETTER BUSINESS</span>
        <em>成都修茈科技有限公司 · xiu-ci.com</em>
        <a class="btn btn-primary btn-sm" href="/capabilities/catalog.html">浏览完整能力目录</a>
      </section>
    </aside>
  </div>

  <section class="section">
    <div class="container">
      <h2>资质与交付</h2>
      <p class="cap-section-note">公司资质与交付保障说明（由原"资质与能力"页并入）。具体资质、合同案例和服务边界以实际公示与合同约定为准。</p>
      <div class="grid grid-4">
        <article class="card"><h3>软件开发能力</h3><p>具备前后端、数据、接口和部署运维的一体化开发能力，主仓库包含完整的后端服务、前端 SPA、桌面壳与移动端工程。</p></article>
        <article class="card"><h3>移动互联网 APP 备案</h3><p>XCAGI Android 个人版/企业版已通过工信部应用程序备案（2026）。</p></article>
        <article class="card"><h3>项目实施理解</h3><p>围绕政企、园区、教育、制造等场景持续沉淀业务认知，已交付涂装、附件包装、考勤等行业 Mod。</p></article>
        <article class="card"><h3>安全与稳定性</h3><p>重视权限、数据隔离、日志审计和可恢复部署；数据库启用 WAL 与在线热备，启动时自动体检并从备份恢复。</p></article>
        <article class="card"><h3>服务机制</h3><p>业务正式开展后，将按合同建立响应、验收与运维机制。</p></article>
      </div>
    </div>
  </section>

  <section class="section">
    <div class="container">
      <h2>本页数字是怎么来的</h2>
      <p>能力目录 <code>data/capabilities/catalog.json</code> 由仓库审计维护；构建脚本 <code>scripts/build_capability_center.py</code> 在生成页面前逐项校验证据：实现路径、自动化测试、CI 工作流、实机截图与录像必须真实存在于当前仓库，否则状态自动降级并在构建报告中留痕。矩阵中每个功能都可点进详情页查看对应证据。目录与页面由 CI 漂移门禁校验一致性，公开数字无法手写、无法夸大。</p>
    </div>
  </section>
</main>
{footer_html()}"""


def render_catalog(data: dict) -> str:
    # script[type=application/json] 内不做 HTML 实体转义（script 内容不会被实体解码），
    # 仅转义 </ 防止提前闭合 script 标签。
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""{header_html("capabilities", "能力目录", "XCAGI 完整能力目录：产品域→模块→功能三级结构，支持搜索与按平台、状态筛选。", "/capabilities/catalog.html")}
<main>
  <section class="page-hero page-hero--slim">
    <div class="container page-hero-inner">
      <div>
        <span class="eyebrow">Capability Catalog</span>
        <h1>能力目录</h1>
        <p>共 <strong>{data['stats']['total']}</strong> 项能力、{data['stats']['modules']} 个模块、{data['stats']['domains']} 个产品域。数字由目录自动统计。</p>
      </div>
      <div class="page-hero-side"><p><a class="btn btn-secondary btn-sm" href="/capabilities/">返回能力中心首页</a></p></div>
    </div>
  </section>
  <section class="section">
    <div class="container">
      <div class="cap-toolbar">
        <input type="search" id="cap-q" class="cap-search" placeholder="搜索功能名称或说明…" aria-label="搜索能力" />
        <select id="cap-domain" aria-label="按产品域筛选"><option value="">全部产品域</option></select>
        <select id="cap-status" aria-label="按状态筛选">
          <option value="">全部状态</option>
          <option value="verified">已验证</option>
          <option value="partial">部分验证</option>
          <option value="implemented">已实现待验证</option>
          <option value="planned">规划中</option>
        </select>
        <select id="cap-platform" aria-label="按平台筛选"><option value="">全部平台</option></select>
      </div>
      <p class="cap-result-note" id="cap-result-note" aria-live="polite"></p>
      <div id="cap-tree"></div>
    </div>
  </section>
</main>
<script id="cap-catalog-data" type="application/json">{payload}</script>
<script src="/capabilities/assets/catalog.js?v=20260919a"></script>
{footer_html()}"""


def evidence_list(items: list[str], cls: str = "") -> str:
    if not items:
        return '<p class="cap-evidence-empty">暂无</p>'
    lis = "".join(
        f'<li><code class="{cls}">{esc(i)}</code></li>' for i in items
    )
    return f'<ul class="cap-evidence-list">{lis}</ul>'


def render_feature(f: dict, dom: dict, mod: dict, data: dict) -> str:
    ev = f["evidence"]
    downgrade_note = ""
    if f["downgraded"]:
        reasons = "；".join(f["downgrade_reasons"])
        downgrade_note = (
            f'<div class="cap-downgrade-note">机器校验：构建时声明状态为「{STATUS_META[f["claimed_status"]]["label"]}」，'
            f"因{esc(reasons)}已自动降级为「{STATUS_META[f['status']]['label']}」。这就是 No Evidence, No Claim 的执行方式。</div>"
        )

    def asset(fid: str, path: str) -> str:
        """证据资产在站点内的相对路径（构建时会把原始文件复制到 assets/evidence/）。"""
        return f"/capabilities/assets/evidence/{esc(fid + '-' + Path(path).name)}"

    media_html = ""
    video_tags = []
    for p in ev.get("videos", []):
        poster = f' poster="{asset(f["id"], ev["screenshots"][0])}"' if ev["screenshots"] else ""
        video_tags.append(
            f'<figure class="cap-shot"><video controls preload="metadata"{poster} src="{asset(f["id"], p)}"></video>'
            f"<figcaption>实机运行录像 / 操作流程（原始文件：{esc(p)}）</figcaption></figure>"
        )
    if video_tags:
        media_html = f'<h3>实机录像 / 操作流程</h3><div class="cap-shots">{"".join(video_tags)}</div>'

    shots_html = ""
    shot_tags = []
    for p in ev["screenshots"]:
        shot_tags.append(
            f'<figure class="cap-shot"><img src="{asset(f["id"], p)}" alt="{esc(f["name"])} 实机证据" loading="lazy" /><figcaption>实机运行证据（原始文件：{esc(p)}）</figcaption></figure>'
        )
    if shot_tags:
        shots_html = f'<h3>实机截图 / 运行证据</h3><div class="cap-shots">{"".join(shot_tags)}</div>'

    commits_html = evidence_list(
        [f"{c['sha']} {c['subject']} ({c['date']})" for c in ev["commits"]]
    )
    verified_time = f.get("verified_at") or "—"
    limitations = (
        "".join(f"<li>{esc(x)}</li>" for x in f.get("limitations", [])) or "<li>暂未记录</li>"
    )
    usage = f.get("usage", "") or "请联系我们获取演示或参阅关联文档。"

    return f"""{header_html("capabilities", f["name"], f"{f['name']}：{f.get('summary', '')}", f"/capabilities/feature/{f['id']}.html")}
<main>
  <section class="page-hero page-hero--slim">
    <div class="container page-hero-inner">
      <div>
        <span class="eyebrow">{esc(dom['name'])} / {esc(mod['name'])}</span>
        <h1>{esc(f['name'])}</h1>
        <div class="cap-feature-meta">{status_badge(f['status'])}{platform_tags(f.get('platforms', []))}</div>
        <p>{esc(f.get('summary', ''))}</p>
      </div>
      <div class="page-hero-side"><p><a class="btn btn-secondary btn-sm" href="/capabilities/catalog.html?domain={esc(dom['id'])}">返回 {esc(dom['name'])}</a></p></div>
    </div>
  </section>

  <section class="section">
    <div class="container cap-feature-top">
      <div class="cap-info-grid">
        <div class="cap-info-block"><h3>功能价值</h3><p>{esc(f.get('summary', ''))}</p></div>
        <div class="cap-info-block"><h3>使用方式</h3><p>{esc(usage)}</p></div>
        <div class="cap-info-block"><h3>所属模块</h3><p>{esc(dom['name'])} / {esc(mod['name'])}</p></div>
        <div class="cap-info-block"><h3>支持平台</h3><p>{platform_tags(f.get('platforms', [])) or '—'}</p></div>
        <div class="cap-info-block"><h3>当前状态</h3><p>{status_badge(f['status'])}（最近验证时间：{esc(verified_time)}）</p></div>
        <div class="cap-info-block"><h3>已知限制</h3><ul class="cap-limitations">{limitations}</ul></div>
      </div>
      {downgrade_note}
    </div>
  </section>

  <section class="section cap-evidence-section">
    <div class="container">
      <h2>技术验证资料</h2>
      <p class="cap-section-note">以下内容由构建脚本从当前仓库自动生成（生成于 {esc(data['generated_at'])}）。路径相对产品仓库根目录；未公开仓库的客户可向我们索取演示与审计说明。</p>
      <div class="cap-evidence-grid">
        <div class="cap-evidence-block"><h3>源码实现</h3>{evidence_list(ev['impl'])}</div>
        <div class="cap-evidence-block"><h3>API 端点</h3>{evidence_list(ev.get('api', []))}</div>
        <div class="cap-evidence-block"><h3>自动化测试</h3>{evidence_list(ev['tests'])}<p class="cap-evidence-note">CI 门禁：{esc('、'.join(ev['ci']) if ev['ci'] else '按仓库 CI 流水线执行')}</p></div>
        <div class="cap-evidence-block"><h3>CI 记录</h3>{evidence_list(ev['ci'])}</div>
        {media_html}
        {shots_html}
        <div class="cap-evidence-block"><h3>关联文档</h3>{evidence_list(ev['docs'])}</div>
        <div class="cap-evidence-block"><h3>验证 commit</h3>{commits_html}</div>
      </div>
    </div>
  </section>
</main>
{footer_html()}"""


# ---------------------------------------------------------------- main

_TS_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC")


def _normalize_ts(text: str) -> str:
    """漂移比对时归一化构建时间戳（生成时间必然变化，不属于漂移）。"""
    return _TS_PATTERN.sub("BUILD-TIME", text)


def write_outputs(data: dict, domains_full: list[dict]) -> dict[str, str]:
    outputs: dict[str, str] = {}
    outputs["capabilities/index.html"] = render_index(data, domains_full)
    outputs["capabilities/catalog.html"] = render_catalog(data)
    for d in domains_full:
        for m in d["modules"]:
            for f in m["features"]:
                outputs[f"capabilities/feature/{f['id']}.html"] = render_feature(f, d, m, data)
    outputs["data/capabilities.json"] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return outputs


def copy_evidence_assets(domains_full: list[dict]) -> list[str]:
    """把目录里声明的截图与录像复制到站点证据目录，供详情页直接引用。"""
    copied = []
    EVIDENCE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for d in domains_full:
        for m in d["modules"]:
            for f in m["features"]:
                for kind in ("screenshots", "videos"):
                    for p in f["evidence"].get(kind, []):
                        src = e(p)
                        dst = EVIDENCE_ASSET_DIR / f"{f['id']}-{Path(p).name}"
                        if src.exists():
                            shutil.copy2(src, dst)
                            copied.append(str(dst.relative_to(WEBSITE_DIR)))
    return copied


def prune_stale_generated(outputs: dict[str, str]) -> list[str]:
    """删除目录里已不在目录数据中的旧生成页。"""
    removed = []
    feat_dir = OUT_DIR / "feature"
    valid = {Path(k).name for k in outputs if k.startswith("capabilities/feature/")}
    if feat_dir.exists():
        for p in feat_dir.glob("*.html"):
            if p.name not in valid:
                removed.append(str(p.relative_to(WEBSITE_DIR)))
                p.unlink()
    return removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="校验已提交文件与目录一致（CI 漂移门禁）")
    args = ap.parse_args()

    data, warnings, domains_full = build()
    outputs = write_outputs(data, domains_full)

    if args.check:
        drift = []
        for rel, content in outputs.items():
            f = WEBSITE_DIR / rel
            if not f.exists():
                drift.append(f"缺失: {rel}")
                continue
            disk = _normalize_ts(f.read_text(encoding="utf-8"))
            mem = _normalize_ts(content)
            if disk == mem:
                continue
            drift.append(f"不一致: {rel}")
            dl, ml = disk.splitlines(), mem.splitlines()
            for i in range(max(len(dl), len(ml))):
                a = dl[i] if i < len(dl) else "<文件结束>"
                b = ml[i] if i < len(ml) else "<重生成结束>"
                if a != b:
                    drift.append(f"    已提交 L{i + 1}: {a.strip()[:160]}")
                    drift.append(f"    重生成 L{i + 1}: {b.strip()[:160]}")
                    break
        for w in warnings:
            print(f"WARN {w}")
        if drift:
            print("能力中心漂移门禁失败：目录与已提交页面不一致。请在仓库根目录运行：")
            print("  python3 '成都修茈科技有限公司/scripts/build_capability_center.py'")
            for d in drift:
                print(f"  - {d}")
            return 1
        print(f"能力中心校验通过：{data['stats']['total']} 项能力，页面与目录一致。")
        return 0

    for rel, content in outputs.items():
        target = WEBSITE_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    copied = copy_evidence_assets(domains_full)
    removed = prune_stale_generated(outputs)

    s = data["stats"]
    print(f"已生成能力中心：{s['total']} 项能力 / {s['modules']} 模块 / {s['domains']} 域")
    print(f"状态分布：{s['by_status']}")
    print(f"最近验证时间：{s['last_verified_at']}")
    print(f"证据资产复制（截图/录像）：{len(copied)} 个；清理过期页：{len(removed)} 个")
    if warnings:
        print(f"\n构建警告 {len(warnings)} 条：")
        for w in warnings:
            print(f"  {w}")
    else:
        print("构建警告：0 条，所有声明均有证据支撑。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
