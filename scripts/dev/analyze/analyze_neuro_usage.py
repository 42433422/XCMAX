"""
Neuro-DDD 使用率统计分析脚本

量化分析项目中 Neuro-DDD 架构的实际使用情况。
支持文本报告与 JSON（供 CI 门禁 ``scripts/check_neuro_migration_thresholds.py`` 使用）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# 定义 Neuro-DDD 核心标识
NEURO_PATTERNS = [
    r"get_neuro_bus\(\)",
    r"publish_event\s*\(",
    r"NeuroEvent\s*\(",
    r"subscribe_event\s*\(",
    r"neuro_bus\.publish",
    r"neuro_bus\.subscribe",
    r"from app\.neuro_bus",
    r"import.*neuro_bus",
    r"NeuroDomain",
    r"DomainChannel",
    r"EventPrimaryDispatcher",
    r"get_command_gateway\(\)",
    r"try_complete_command_reply",
    r"is_event_primary_enabled",
]

# 传统架构标识
TRADITIONAL_PATTERNS = [
    r"@app\.route\s*\(",
    r"@router\.(get|post|put|delete)\s*\(",
    r"db\.session\.",
    r"SessionLocal\(\)",
    r"from app\.services\.",
    r"from app\.utils\.",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def analyze_file(file_path: Path) -> dict | None:
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        neuro_matches: list[str] = []
        traditional_matches: list[str] = []
        for pattern in NEURO_PATTERNS:
            neuro_matches.extend(re.findall(pattern, content, re.IGNORECASE))
        for pattern in TRADITIONAL_PATTERNS:
            traditional_matches.extend(re.findall(pattern, content, re.IGNORECASE))
        return {
            "neuro_count": len(neuro_matches),
            "traditional_count": len(traditional_matches),
            "neuro_patterns": list(set(neuro_matches)),
            "traditional_patterns": list(set(traditional_matches)),
        }
    except OSError:
        return None


def scan_directory(root_dir: Path, extensions: list[str] | None = None) -> dict:
    if extensions is None:
        extensions = [".py"]
    stats: dict = defaultdict(lambda: {"neuro": 0, "traditional": 0, "files": []})
    skip_parts = {"node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"}

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in skip_parts]
        for file in files:
            if not any(file.endswith(ext) for ext in extensions):
                continue
            file_path = Path(root) / file
            result = analyze_file(file_path)
            if not result or (result["neuro_count"] == 0 and result["traditional_count"] == 0):
                continue
            rel_path = file_path.relative_to(root_dir)
            parts = rel_path.parts
            module = parts[0] if len(parts) > 1 else "root"
            stats[module]["files"].append(
                {
                    "path": str(rel_path),
                    "neuro": result["neuro_count"],
                    "traditional": result["traditional_count"],
                }
            )
            stats[module]["neuro"] += result["neuro_count"]
            stats[module]["traditional"] += result["traditional_count"]
    return dict(stats)


def build_layer_summary(stats: dict) -> dict:
    """Map top-level app/ subdirs to architecture layers."""
    layer_map = {
        "application": "application",
        "services": "services",
        "fastapi_routes": "routes",
        "neuro_bus": "neuro_bus",
        "domain": "domain",
    }
    layers: dict[str, dict] = defaultdict(lambda: {"neuro": 0, "traditional": 0})
    for module, data in stats.items():
        layer = layer_map.get(module, "other")
        layers[layer]["neuro"] += data["neuro"]
        layers[layer]["traditional"] += data["traditional"]
    out: dict[str, dict] = {}
    for layer, data in layers.items():
        total = data["neuro"] + data["traditional"]
        out[layer] = {
            "neuro": data["neuro"],
            "traditional": data["traditional"],
            "total": total,
            "neuro_pct": round((data["neuro"] / total * 100) if total else 0.0, 2),
        }
    return out


def _migrated_http_domains(repo_root: Path) -> tuple[str, ...]:
    """Parse app_service_pair_registry without importing app (avoids heavy deps)."""
    registry = repo_root / "app/application/app_service_pair_registry.py"
    if not registry.is_file():
        return ()
    lines = registry.read_text(encoding="utf-8").splitlines()
    domains: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() not in ('"v2",', "'v2',"):
            continue
        for j in range(i, -1, -1):
            if "AppServicePair" in lines[j]:
                for k in range(j + 1, i):
                    m = re.match(r'\s*"([a-z_]+)",\s*$', lines[k])
                    if m:
                        domains.append(m.group(1))
                        break
                break
    return tuple(domains)


def build_json_report(stats: dict, repo_root: Path) -> dict:
    layers = build_layer_summary(stats)
    total_neuro = sum(d["neuro"] for d in stats.values())
    total_traditional = sum(d["traditional"] for d in stats.values())
    grand = total_neuro + total_traditional
    migrated = _migrated_http_domains(repo_root)
    return {
        "layers": layers,
        "modules": {
            k: {
                "neuro": v["neuro"],
                "traditional": v["traditional"],
                "neuro_pct": round(
                    (v["neuro"] / (v["neuro"] + v["traditional"]) * 100)
                    if (v["neuro"] + v["traditional"])
                    else 0.0,
                    2,
                ),
                "file_count": len(v["files"]),
            }
            for k, v in stats.items()
        },
        "overall": {
            "neuro": total_neuro,
            "traditional": total_traditional,
            "neuro_pct": round((total_neuro / grand * 100) if grand else 0.0, 2),
        },
        "migrated_http_domains": list(migrated),
    }


def print_report(stats: dict) -> None:
    print("\n" + "=" * 80)
    print("Neuro-DDD 使用率统计报告")
    print("=" * 80)
    total_neuro = 0
    total_traditional = 0
    module_stats = []
    for module, data in sorted(stats.items(), key=lambda x: x[1]["neuro"], reverse=True):
        neuro_count = data["neuro"]
        traditional_count = data["traditional"]
        total = neuro_count + traditional_count
        if total == 0:
            continue
        neuro_ratio = neuro_count / total * 100
        module_stats.append(
            {
                "module": module,
                "neuro": neuro_count,
                "traditional": traditional_count,
                "total": total,
                "ratio": neuro_ratio,
                "files": len(data["files"]),
            }
        )
        total_neuro += neuro_count
        total_traditional += traditional_count
    print(f"\n{'模块':<25} {'Neuro':>8} {'Traditional':>12} {'Total':>8} {'Neuro%':>10} {'Files':>8}")
    print("-" * 80)
    for stat in module_stats:
        print(
            f"{stat['module']:<25} {stat['neuro']:>8} {stat['traditional']:>12} "
            f"{stat['total']:>8} {stat['ratio']:>9.1f}% {stat['files']:>8}"
        )
    print("-" * 80)
    grand_total = total_neuro + total_traditional
    overall_ratio = (total_neuro / grand_total * 100) if grand_total else 0
    print(
        f"{'TOTAL':<25} {total_neuro:>8} {total_traditional:>12} "
        f"{grand_total:>8} {overall_ratio:>9.1f}%"
    )
    layers = build_layer_summary(stats)
    print("\n架构层摘要:")
    for layer, data in sorted(layers.items()):
        print(f"  {layer}: neuro_pct={data['neuro_pct']}% ({data['neuro']}/{data['total']})")


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description="Analyze Neuro-DDD usage in app/")
    parser.add_argument("--json", metavar="PATH", help="Write JSON report to PATH")
    parser.add_argument("--app-dir", default=str(root / "app"), help="Directory to scan")
    args = parser.parse_args()

    app_dir = Path(args.app_dir)
    if not app_dir.is_dir():
        print(f"ERROR: app dir not found: {app_dir}", file=sys.stderr)
        return 2

    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    print(f"\n分析目录：{app_dir}")
    stats = scan_directory(app_dir)
    print_report(stats)
    report = build_json_report(stats, root)
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nJSON 报告已写入: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
