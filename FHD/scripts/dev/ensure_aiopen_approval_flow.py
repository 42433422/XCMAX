"""幂等创建 AIOPEN 危险操作审批流程（默认 ``aiopen_danger_operation``）。

AIOPEN 的危险操作复用既有审批中心：流程不存在时提交会返回
``APPROVAL_FLOW_NOT_CONFIGURED`` 并失败关闭。本脚本只补齐流程与启用节点，
不修改既有流程定义，也不写入任何业务数据。

用法::

    python scripts/dev/ensure_aiopen_approval_flow.py --approver-id 1
    python scripts/dev/ensure_aiopen_approval_flow.py --dry-run

未显式传 ``--approver-id`` 时，自动取该库内启用的 admin / superadmin 账号作为
审批人；若一个也找不到则退出码 2，避免创建无人可批的空流程。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.application.aiopen.approval_bridge import DEFAULT_FLOW_KEY
from app.db.models.approval import ApprovalFlow, ApprovalFlowNode
from app.db.models.user import User
from app.db.session import get_db

REVIEW_ROLES = ("admin", "superadmin", "super_admin", "owner")


def _resolve_approvers(db, explicit: list[int]) -> list[int]:
    if explicit:
        return sorted({int(item) for item in explicit})
    users = (
        db.query(User)
        .filter(User.is_active == True)
        .filter(User.role.in_(REVIEW_ROLES))
        .order_by(User.id.asc())
        .all()
    )
    return sorted({int(user.id) for user in users if user.id is not None})


def ensure_flow(
    *,
    flow_key: str,
    flow_name: str,
    approver_ids: list[int],
    dry_run: bool,
) -> dict:
    report: dict = {"flow_key": flow_key, "changed": [], "approver_ids": approver_ids}
    with get_db() as db:
        flow = db.query(ApprovalFlow).filter(ApprovalFlow.flow_key == flow_key).first()
        if flow is None:
            report["changed"].append("flow_created")
            flow = ApprovalFlow(
                flow_key=flow_key,
                flow_name=flow_name,
                description="AIOPEN 外部 Agent 危险操作（删除/批量/退款等）人工审批",
                industry="通用",
                business_type="aiopen.danger_operation",
                node_type="serial",
                allow_transfer=True,
                allow_delegate=False,
                allow_withdraw=True,
                is_active=True,
                is_deleted=False,
            )
            if dry_run:
                report["dry_run"] = True
                report["created"] = False
                return report
            db.add(flow)
            db.flush()
        elif not flow.is_active or flow.is_deleted:
            report["changed"].append("flow_activated")
            if not dry_run:
                flow.is_active = True
                flow.is_deleted = False
        active_nodes = (
            db.query(ApprovalFlowNode)
            .filter(ApprovalFlowNode.flow_id == flow.id, ApprovalFlowNode.is_active == True)
            .order_by(ApprovalFlowNode.node_order.asc())
            .all()
        )
        report["flow_id"] = flow.id
        report["node_ids"] = [node.id for node in active_nodes]
        if not active_nodes:
            if not approver_ids:
                report["error"] = "no_approver"
                report["changed"].append("node_skipped")
                return report
            report["changed"].append("node_created")
            if not dry_run:
                db.add(
                    ApprovalFlowNode(
                        flow_id=flow.id,
                        node_name="AIOPEN 危险操作审批",
                        node_order=1,
                        node_type="serial",
                        approver_type="user",
                        approver_ids=json.dumps(approver_ids),
                        min_approvals=1,
                        timeout_hours=48,
                        timeout_action="notify",
                        is_active=True,
                    )
                )
        else:
            first = active_nodes[0]
            missing = sorted(set(approver_ids) - set(json.loads(first.approver_ids or "[]")))
            if missing and approver_ids:
                report["changed"].append("node_approvers_extended")
                if not dry_run:
                    merged = sorted(set(json.loads(first.approver_ids or "[]")) | set(approver_ids))
                    first.approver_ids = json.dumps(merged)
        if dry_run:
            report["dry_run"] = True
            report.pop("flow_id", None)
            return report
        db.flush()
        report["flow_id"] = flow.id
        report["node_ids"] = [
            node.id
            for node in db.query(ApprovalFlowNode)
            .filter(
                ApprovalFlowNode.flow_id == flow.id,
                ApprovalFlowNode.is_active == True,
            )
            .order_by(ApprovalFlowNode.node_order.asc())
            .all()
        ]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flow-key", default=DEFAULT_FLOW_KEY)
    parser.add_argument("--flow-name", default="AIOPEN 危险操作审批")
    parser.add_argument(
        "--approver-id",
        type=int,
        action="append",
        default=[],
        help="审批人用户 ID，可重复；缺省取 admin/superadmin",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with get_db() as db:
        approvers = _resolve_approvers(db, args.approver_id)
    if not approvers:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "no_approver",
                    "message": "库中没有可用的 admin/superadmin 账号，请显式指定 --approver-id。",
                },
                ensure_ascii=False,
            )
        )
        return 2

    report = ensure_flow(
        flow_key=args.flow_key,
        flow_name=args.flow_name,
        approver_ids=approvers,
        dry_run=args.dry_run,
    )
    report["success"] = "error" not in report
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
