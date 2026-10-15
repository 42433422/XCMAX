#!/usr/bin/env python3
"""merged-into-main 净速率指标（net_rate）
公式（与 trae-windows 对齐，discussion-001）：
  net_rate = Σ(merged PR 的 diff 权重) / Σ(人工介入分钟)
  - diff 权重 = 净增删行/100（封顶 5），revert/热修 记负权重
  - 人工介入分钟 ≈ PR 从 opened 到 merged 期间人类 review 评论数 × 10（近似，可后续精化）
数据源：GitHub API（gh）。输出 JSON 到 stdout + 写 metrics/net_rate.json
"""
import json, subprocess, sys, datetime, pathlib

REPO = "42433422/XCMAX"
WINDOW_DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7

def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None

since = (datetime.datetime.utcnow() - datetime.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")

prs = gh("pr", "list", "--repo", REPO, "--state", "merged", "--limit", "200",
         "--json", "number,mergedAt,additions,deletions,title,url") or []
merged = [p for p in prs if p.get("mergedAt", "") >= since]

total_weight = 0.0
total_human_min = 0.0
items = []
for p in merged:
    diff_w = min(5.0, (p.get("additions", 0) + p.get("deletions", 0)) / 100.0)
    reverted = "revert" in (p.get("title", "") or "").lower()
    if reverted:
        diff_w = -abs(diff_w)
    # 人工介入近似：人类 review 评论数 ×10 分钟
    revs = gh("pr", "view", str(p["number"]), "--repo", REPO,
              "--json", "reviews", "--jq", "[.reviews[] | select(.author.login != \"github-actions[bot]\")] | length")
    human_min = (revs or 0) * 10
    total_weight += diff_w
    total_human_min += human_min
    items.append({"pr": p["number"], "weight": round(diff_w, 2), "human_min": human_min})

net_rate = round(total_weight / (total_human_min / 60.0), 2) if total_human_min else None
out = {
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    "window_days": WINDOW_DAYS,
    "merged_prs": len(merged),
    "total_diff_weight": round(total_weight, 2),
    "total_human_minutes": total_human_min,
    "net_rate_weight_per_hour_human": net_rate,
    "note": "净速率=被集成产出/人类瓶颈资源；revert 负权重；分母为 review 近似",
    "items": items[:30],
}
dest = pathlib.Path("metrics"); dest.mkdir(exist_ok=True)
(dest / "net_rate.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps(out, ensure_ascii=False, indent=2))