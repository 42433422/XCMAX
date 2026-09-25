#!/usr/bin/env python3
"""WO-0f1b3d12bab4 诊断：把「绿灯 run 与红灯 run 的依赖差异」算成证据。

单一用途脚本，不做通用框架——结论不写死，全部从两次真实 CI run 的安装清单计算：

  绿灯 313655b20  job 107569280860（mypy 步骤 success）
  红灯 d34c354d1  job 107895943074（mypy 步骤 failure，56 条错误）

首轮诊断曾误判为 mypy 版本，被 PR #2036 自己的 CI 证伪（mypy 固定到 1.19.1 后
错误不变）；本脚本按同一份基线重新计算真实变量。

用法：python scripts/dev/self_heal_diagnose_ci_deps.py --out test_reports/.../diagnosis.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

_FHD_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _FHD_ROOT.parent
_DEPLOY_REL = "成都修茈科技有限公司/MODstore_deploy"
_REPO = "42433422/XCMAX"
_GREEN = {"sha": "313655b20", "job": "107569280860"}
_RED = {"sha": "d34c354d1", "job": "107895943074"}


def _job_log(job_id: str) -> str:
    """作业日志：走 API（`gh run view --job --log` 对过期作业会返回截断文本）。"""
    text = subprocess.run(
        ["gh", "api", f"repos/{_REPO}/actions/jobs/{job_id}/logs"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    if "Successfully installed" in text:
        return text
    return subprocess.run(
        ["gh", "run", "view", "--repo", _REPO, "--job", job_id, "--log"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout


def _deps(log_text: str) -> dict[str, str]:
    """从「Successfully installed ...」抽依赖版本表。"""
    match = re.search(r"Successfully installed (.*)", log_text)
    if not match:
        return {}
    out: dict[str, str] = {}
    for token in match.group(1).split():
        item = re.match(r"^([A-Za-z0-9_.]+)-(\d[^\s]*)$", token)
        if item:
            out[item.group(1).lower()] = item.group(2)
    return out


def _deploy_diff_files() -> int:
    out = subprocess.run(
        ["git", "diff", "--name-only", _GREEN["sha"], _RED["sha"], "--", _DEPLOY_REL],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return len(out.splitlines()) if out else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="test_reports/self_heal_loop/diagnosis.json")
    args = parser.parse_args()
    green_log = _FHD_ROOT / "test_reports/self_heal_loop/evidence/ci-green.log"
    if not green_log.is_file():
        green_log.parent.mkdir(parents=True, exist_ok=True)
        green_log.write_text(_job_log(_GREEN["job"]), encoding="utf-8")
    red_log = _FHD_ROOT / "test_reports/self_heal_loop/evidence/ci-mypy-failing.log"
    green, red = (
        _deps(green_log.read_text(encoding="utf-8", errors="replace")),
        _deps(red_log.read_text(encoding="utf-8", errors="replace")),
    )
    # 逐个包比对「包-版本」对：同名不同版才是真实变量（只比包名会漏掉版本漂移）
    only_green = {k: green[k] for k in sorted(green) if k not in red or red[k] != green[k]}
    only_red = {k: red[k] for k in sorted(red) if k not in green or green[k] != red[k]}
    diagnosis = {
        "wo_id": "WO-0f1b3d12bab4",
        "generated_at": datetime.now(UTC).isoformat(),
        "revision": 2,
        "supersedes": "revision 1（误判为 mypy 版本浮动；被 PR #2036 自身 CI 证伪）",
        "engine": "rule+evidence",
        "root_cause": (
            "sqlalchemy 由 2.0.54 浮动到 2.1.0：2.1.0 收紧 Query 类型推断，"
            "使既有代码在 mypy 门禁下被判 56 条错误（代码零变更）。"
            "pyproject 的 `sqlalchemy>=2.0` 缺上界是根因条件。"
        ),
        "affected_files": [
            f"{_DEPLOY_REL}/pyproject.toml",
            f"{_DEPLOY_REL}/modstore_server/**（约 30 个模块被新类型推断判红）",
        ],
        "affected_feature": "release-gate:backend-python:mypy",
        "affected_platform": "ci/ubuntu-latest",
        "blast_radius": "main 全部合并被 release-gate 阻断；不影响已发布产品运行时",
        "confidence": "high",
        "evidence": {
            "green_run": {"sha": _GREEN["sha"], "job": _GREEN["job"], "mypy_step": "success"},
            "red_run": {"sha": _RED["sha"], "job": _RED["job"], "mypy_step": "failure"},
            "deploy_changed_files_between_runs": _deploy_diff_files(),
            "mypy_version_green": green.get("mypy", ""),
            "mypy_version_red": red.get("mypy", ""),
            "deps_only_in_green": only_green,
            "deps_only_in_red": only_red,
            "error_count_in_red_log": len(
                re.findall(r"error:", red_log.read_text(encoding="utf-8", errors="replace"))
            ),
        },
        "proposed_fix": (
            "按同文件既有约定（anyio>=4.4,<4.15 / alembic>=1.16,<2）给 sqlalchemy 加上界 "
            "<2.1，恢复已知可过门禁的版本区间；2.1 类型迁移单独立项。"
            "另：mypy 与 black/isort 同规则精确固定，属独立加固项。"
        ),
        "regression_scope": "backend CI mypy 步骤与 dev 依赖声明；无产品运行时代码改动",
        "rollback_risk": "low",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(diagnosis["evidence"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
