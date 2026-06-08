"""注册 skill-doc-sync 为数据库中的 ESkill 记录。

用法：
    python -m modstore_server.scripts.register_doc_sync_eskill [--force]

此脚本为 doc-knowledge-curator 员工的 skill-doc-sync 创建 ESkill + ESkillVersion 记录，
使 ESkill Runtime 能加载和执行该技能。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = MODSTORE_ROOT.parent
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


SKILL_DOC_SYNC_STATIC_LOGIC = {
    "type": "pipeline",
    "steps": [
        {
            "type": "set_value",
            "key": "change_signals",
            "value": "{}",
            "description": "初始化变更信号",
        },
        {
            "type": "tool_call",
            "tool": "doc_change_detector",
            "description": "检测文档变更",
        },
        {
            "type": "tool_call",
            "tool": "markdown_lint",
            "description": "Markdown lint 校验",
        },
        {
            "type": "tool_call",
            "tool": "doc_consistency_check",
            "description": "文档一致性校验",
        },
        {
            "type": "template_transform",
            "template": json.dumps(
                {
                    "status": "${status}",
                    "changed_docs": "${changed_docs}",
                    "markdown_lint_errors": "${markdown_lint_errors}",
                    "diff_summary": "${diff_summary}",
                },
                ensure_ascii=False,
            ),
            "output_var": "eskill_result",
            "description": "输出文档同步结果",
        },
    ],
}

SKILL_DOC_SYNC_TRIGGER_POLICY = {
    "type": "quality_gate",
    "condition": "markdown_lint_errors > 0 || doc_yaml_inconsistent == true",
    "description": "当 Markdown lint 有错误或文档与 yaml 不一致时触发动态阶段",
}

SKILL_DOC_SYNC_QUALITY_GATE = {
    "markdown_lint_errors": 0,
    "doc_yaml_consistent": True,
    "description": "验收标准：lint 无错误，文档与 yaml 一致",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register skill-doc-sync ESkill for doc-knowledge-curator"
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite existing ESkill if it exists"
    )
    args = parser.parse_args()

    from modstore_server.models import ESkill, ESkillVersion, User, get_session_factory

    sf = get_session_factory()
    with sf() as session:
        admin = (
            session.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()
        )  # noqa: E712
        if not admin:
            print("No admin user found in DB.", file=sys.stderr)
            return 3
        admin_id = int(admin.id)

    with sf() as session:
        existing = (
            session.query(ESkill)
            .filter(ESkill.user_id == admin_id, ESkill.name == "skill-doc-sync")
            .first()
        )

        if existing and not args.force:
            print(
                f"[SKIP] ESkill 'skill-doc-sync' already exists (id={existing.id}, version={existing.active_version})"
            )
            return 0

        if existing and args.force:
            session.delete(existing)
            session.flush()
            print(f"[DELETE] Removed existing ESkill 'skill-doc-sync' (id={existing.id})")

        skill = ESkill(
            user_id=admin_id,
            name="skill-doc-sync",
            domain="文档资产同步与维护",
            description="doc-knowledge-curator 的核心 ESkill：读取变更信号 → 定位需更新的 .md → 生成 diff → markdownlint 校验 → 一致性检查",
            active_version=1,
        )
        session.add(skill)
        session.flush()
        skill_id = int(skill.id)

        version = ESkillVersion(
            eskill_id=skill_id,
            version=1,
            static_logic_json=json.dumps(SKILL_DOC_SYNC_STATIC_LOGIC, ensure_ascii=False, indent=2),
            trigger_policy_json=json.dumps(
                SKILL_DOC_SYNC_TRIGGER_POLICY, ensure_ascii=False, indent=2
            ),
            quality_gate_json=json.dumps(SKILL_DOC_SYNC_QUALITY_GATE, ensure_ascii=False, indent=2),
            note="Initial version from register_doc_sync_eskill script",
        )
        session.add(version)
        session.commit()

        print(
            f"[OK] ESkill 'skill-doc-sync' registered: id={skill_id}, version=1, user_id={admin_id}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
