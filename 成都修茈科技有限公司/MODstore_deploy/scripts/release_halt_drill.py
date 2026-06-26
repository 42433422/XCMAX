#!/usr/bin/env python3
"""M4 · 发布熔断 / 自动回滚演练（确定性，无需真实部署）。

对标大厂：放量前必须证明「指标恶化 → 自动停 / 不放量」。本演练在进程内：
1. 注入一条 **失败** 的 post_deploy_smoke 状态；
2. 断言 ``slo_halt_blocks_auto_merge()`` == True（次日 auto-merge 被阻断）；
3. 断言 ``should_auto_approve_staged(...)`` == False（低风险也不放量）；
4. 注入一条 **健康** 状态，断言 auto-approve 恢复（开启时）；
5. 恢复原状态文件；打印 PASS/FAIL 与回滚 runbook 计时提醒。

用法（CVM 或本机，MODstore_deploy 根目录）：
    MODSTORE_SLO_HALT_AUTO_MERGE=1 MODSTORE_OPS_STAGED_AUTO_APPROVE=1 \
        python3 scripts/release_halt_drill.py
退出码：0=演练通过（安全网生效）；1=演练失败（安全网未生效，禁止开 auto-approve）。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _set_drill_env() -> None:
    os.environ.setdefault("MODSTORE_SLO_HALT_AUTO_MERGE", "1")
    os.environ.setdefault("MODSTORE_RELEASE_SLO_HALT", "1")
    os.environ.setdefault("MODSTORE_OPS_STAGED_AUTO_APPROVE", "1")


def _force_live_smoke_fail() -> None:
    """让实时 post_deploy_smoke 确定性失败：探针指向不可达端口（连接拒绝）。"""
    os.environ["MODSTORE_POST_DEPLOY_SMOKE_ENABLED"] = "1"
    os.environ["MODSTORE_POST_DEPLOY_SMOKE_TIMEOUT_SEC"] = "3"
    os.environ["MODSTORE_DEPLOY_HEALTH_URL"] = "http://127.0.0.1:1/health"
    os.environ["MODSTORE_POST_DEPLOY_MARKET_URL"] = "http://127.0.0.1:1/market/download"


def _disable_live_smoke() -> None:
    """健康相位：跳过实时探针（skipped → halt 不激活），仅验证状态文件门恢复。"""
    os.environ["MODSTORE_POST_DEPLOY_SMOKE_ENABLED"] = "0"


def _write_state(ok: bool) -> Path:
    from modstore_server.post_deploy_smoke import _state_file_path  # type: ignore

    path = _state_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "ok": ok,
                "skipped": False,
                "probes": [
                    {"name": "health", "url": "drill", "status": 200 if ok else 503, "ok": ok}
                ],
                "ran_at": datetime.now(timezone.utc).isoformat(),
                "drill": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def main() -> int:
    _set_drill_env()
    from modstore_server.ops_staged_auto_approve import should_auto_approve_staged
    from modstore_server.post_deploy_smoke import _state_file_path, slo_halt_blocks_auto_merge

    state_path = _state_file_path()
    backup = state_path.read_text(encoding="utf-8") if state_path.is_file() else None
    failures: list[str] = []
    try:
        # 1+2+3 · 失败相位：实时 smoke 失败 + 失败状态文件 → 两道安全网必须阻断
        _force_live_smoke_fail()
        _write_state(ok=False)
        if not slo_halt_blocks_auto_merge():
            failures.append("状态文件失败但 slo_halt_blocks_auto_merge() 未阻断次日 auto-merge")
        if should_auto_approve_staged(files_changed_count=1, diff_summary="app/foo.py | 1 +"):
            failures.append("实时 smoke 失败但 should_auto_approve_staged() 仍放量")
        print("[drill] 失败相位 → 安全网阻断:", not failures)

        # 4 · 健康相位：实时 smoke 跳过 + 健康状态文件 → 放量恢复
        _disable_live_smoke()
        _write_state(ok=True)
        if slo_halt_blocks_auto_merge():
            failures.append("状态文件健康但 slo_halt_blocks_auto_merge() 仍阻断（误阻断）")
        if not should_auto_approve_staged(files_changed_count=1, diff_summary="app/foo.py | 1 +"):
            failures.append("smoke 恢复健康但 should_auto_approve_staged() 仍拒绝（误阻断）")
        print("[drill] 健康相位 → 放量恢复:", not failures)
    finally:
        if backup is not None:
            state_path.write_text(backup, encoding="utf-8")
        elif state_path.is_file():
            state_path.unlink()

    print("")
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        print("[结论] 安全网未生效 → 禁止开 MODSTORE_OPS_STAGED_AUTO_APPROVE")
        return 1
    print("[PASS] SLO halt 安全网生效：smoke 失败自动阻断放量，健康后恢复。")
    print("[提醒] 真实回滚演练计时见 docs/runbooks/ROLLBACK.md（目标 15 分钟内原子切换）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
