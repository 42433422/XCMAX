"""从自然语言描述生成 employee_pack mod（含 manifest.json + .xcemp 包）。

进化状态闭环（2026-07-20）：
  系统自己写 mod 代码 — 本脚本是「生成器」入口：
  LLM 生成 manifest → build_employee_pack_zip 打包 → 落地到 modstore library

用法：
    # dry-run（只看 LLM 生成的 manifest，不写盘）
    python scripts/generate_mod_from_description.py \\
        --description "员工信息访谈员：通过结构化提问补全元数据" \\
        --id employee-interview-assistant \\
        --name "员工信息访谈员" \\
        --dry-run

    # apply（写盘到 modstore library + FHD/mods/_employees/）
    python scripts/generate_mod_from_description.py \\
        --description "..." \\
        --id new-employee \\
        --name "新员工" \\
        --apply

依赖：modstore_server.employee_ai_scaffold.build_employee_pack_zip
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from modstore_server.operational_errors import RECOVERABLE_ERRORS

# 注入 modstore_server 包路径
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _call_llm(prompt: str, api_key: str) -> dict[str, Any]:
    """调用 LLM 生成 manifest.json 内容。"""
    if not api_key:
        return {"ok": False, "error": "XCAGI_LLM_API_KEY 未配置"}
    base = os.environ.get("XCAGI_LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("XCAGI_LLM_MODEL", "deepseek-chat")
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是 MODstore 员工包生成助手。"
                        "根据用户描述，输出符合 employee_config_v2 规范的 JSON manifest。"
                        "字段必须包括：id, name, version, author, description, artifact(=employee_pack), "
                        "scope(=global), dependencies, employee, employee_config_v2(identity/perception/memory/"
                        "cognition/schedule/actions/collaboration/metadata/workspace_policy), "
                        "workflow_employees, backend, depends_on, triggers。"
                        "actions.handlers 必须是 echo/llm_md/webhook/agent 之一。"
                        "返回纯 JSON（无 markdown 包裹）。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 3000,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        # 去掉 markdown 包裹
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return {"ok": False, "error": "LLM 响应未包含 JSON", "raw": content[:500]}
        manifest = json.loads(m.group(0))
        manifest["ok"] = True
        return manifest
    except RECOVERABLE_ERRORS as exc:  # noqa: BLE001
        return {"ok": False, "error": f"LLM 调用失败：{exc}"}


def _validate_manifest(manifest: dict[str, Any], expected_id: str, expected_name: str) -> list[str]:
    """校验 manifest 必填字段。返回错误列表（空表示通过）。"""
    errs: list[str] = []
    if str(manifest.get("id") or "").strip() != expected_id:
        errs.append(f"id 应为 {expected_id}，实际为 {manifest.get('id')!r}")
    if str(manifest.get("name") or "").strip() != expected_name:
        errs.append(f"name 应为 {expected_name}，实际为 {manifest.get('name')!r}")
    if str(manifest.get("artifact") or "").strip() != "employee_pack":
        errs.append(f"artifact 应为 employee_pack，实际为 {manifest.get('artifact')!r}")
    v2 = manifest.get("employee_config_v2")
    if not isinstance(v2, dict):
        errs.append("employee_config_v2 缺失")
    else:
        actions = v2.get("actions") or {}
        handlers = actions.get("handlers") if isinstance(actions, dict) else None
        if not isinstance(handlers, list) or not handlers:
            errs.append("employee_config_v2.actions.handlers 必须为非空数组")
        else:
            allowed = {"echo", "llm_md", "webhook", "agent"}
            invalid = [h for h in handlers if h not in allowed]
            if invalid:
                errs.append(f"handlers 含非法值：{invalid}（允许：{sorted(allowed)}）")
    return errs


def _build_prompt(args: argparse.Namespace) -> str:
    return (
        f"请生成一个 employee_pack mod 的 manifest.json。\n\n"
        f"员工 ID: {args.id}\n"
        f"员工名称: {args.name}\n"
        f"作者: {args.author}\n"
        f"版本: {args.version}\n"
        f"描述: {args.description}\n\n"
        f"参考字段：employee_config_v2.identity.{{'area','domain'}} 由描述推导；"
        f"actions.handlers 默认 ['echo']；schedule.cron 默认 '0 3 * * *'（每日 03:00 UTC）；"
        f"system_prompt 简洁专业，约 200 字；workspace_policy.scope_globs 默认空数组。"
    )


def run(args: argparse.Namespace) -> int:
    logger.info("generating manifest: id=%s name=%s", args.id, args.name)
    prompt = _build_prompt(args)
    plan = _call_llm(prompt, args.llm_api_key)
    if not plan.get("ok"):
        logger.error("LLM 生成失败：%s", plan.get("error"))
        print(json.dumps({"ok": False, "error": plan.get("error")}, ensure_ascii=False))
        return 1

    # 提取 manifest 字段（剥离 ok 标记）
    manifest = {k: v for k, v in plan.items() if k != "ok"}
    # 强制覆盖关键字段，防止 LLM 偏离
    manifest["id"] = args.id
    manifest["name"] = args.name
    manifest["version"] = args.version
    manifest["author"] = args.author
    manifest["artifact"] = "employee_pack"
    manifest["scope"] = "global"

    errs = _validate_manifest(manifest, args.id, args.name)
    if errs:
        logger.error("manifest 校验失败：%s", errs)
        print(
            json.dumps(
                {"ok": False, "errors": errs, "manifest": manifest}, ensure_ascii=False, indent=2
            )
        )
        return 2

    if args.dry_run:
        print(
            json.dumps(
                {"ok": True, "manifest": manifest, "dry_run": True}, ensure_ascii=False, indent=2
            )
        )
        return 0

    # 打包为 .xcemp
    try:
        from modstore_server.employee_ai_scaffold import build_employee_pack_zip
    except ImportError as exc:
        logger.error("无法导入 build_employee_pack_zip：%s", exc)
        return 3

    zip_bytes = build_employee_pack_zip(args.id, manifest, include_runtime=True)

    # 写入 modstore library
    try:
        from modstore_server.mod_scaffold_runner import modstore_library_path
    except ImportError as exc:
        logger.error("无法导入 modstore_library_path：%s", exc)
        return 3

    lib = modstore_library_path()
    pack_dir = lib / args.id
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    xcemp_path = lib / f"{args.id}-{args.version}.xcemp"
    xcemp_path.write_bytes(zip_bytes)
    logger.info("xcemp written: %s (%d bytes)", xcemp_path, len(zip_bytes))

    # 镜像到 FHD/mods/_employees/（与现有骨架对齐）
    fhd_mods_dir = Path(__file__).resolve().parents[2] / "FHD" / "mods" / "_employees" / args.id
    fhd_mods_dir.mkdir(parents=True, exist_ok=True)
    (fhd_mods_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "ok": True,
                "pkg_id": args.id,
                "version": args.version,
                "library_path": str(pack_dir),
                "xcemp_path": str(xcemp_path),
                "fhd_mirror": str(fhd_mods_dir),
                "generated_at": _utc_now(),
                "llm_used": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="从自然语言描述生成 employee_pack mod")
    parser.add_argument("--id", required=True, help="mod id（kebab-case）")
    parser.add_argument("--name", required=True, help="mod 名称（中文）")
    parser.add_argument("--description", required=True, help="自然语言描述")
    parser.add_argument("--author", default="ai-generator")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--llm-api-key", default=os.environ.get("XCAGI_LLM_API_KEY", ""))
    parser.add_argument("--dry-run", action="store_true", help="只输出 manifest，不写盘")
    parser.add_argument(
        "--apply", action="store_true", help="实际写盘到 modstore library + FHD/mods/"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(args))


if __name__ == "__main__":
    main()
