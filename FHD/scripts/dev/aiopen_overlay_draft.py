"""为 AIOPEN 目录生成语义 overlay 草稿，供人工审核后入库。

草稿写入 ``overlay/drafts/``，运行时**不加载**；审核通过后把条目移入
``overlay/generated/*.yaml`` 才会进入系统地图。模型只负责起草，不参与风险分级、
scope 计算或权限判断。

用法（在 FHD/ 下，需已配置模型 Provider）::

    python scripts/dev/aiopen_overlay_draft.py --limit 40
    python scripts/dev/aiopen_overlay_draft.py --domains products,customers --batch-size 8
    python scripts/dev/aiopen_overlay_draft.py --catalog-json /tmp/catalog.json --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

FHD_ROOT = Path(__file__).resolve().parents[2]
DRAFT_DIR = FHD_ROOT / "app" / "application" / "aiopen" / "overlay" / "drafts"

_SYSTEM_PROMPT = """你是企业软件的能力目录编辑。给你一批后端接口（operation），
请为每个接口写一条**保守、可核对**的语义说明，帮助外部 AI 判断何时调用它。

规则：
1. 只依据给定的 method/path/summary/risk/domain 推断，不要编造业务规则、字段名或数字。
2. 无法确定时，when_to_use 写成「用于…（按路径与摘要推断）」并留空其余不确定项。
3. side_effects 只写可由 HTTP 方法明确推出的副作用，例如「写数据库」「删除资源」；
   GET 通常为空数组。
4. preconditions 只写通用前置条件，例如「已登录」「具备对应业务权限」。
5. 只输出 JSON 数组，不要 Markdown 代码块以外的任何文字。每个元素字段：
   operation_id（必须与输入一致）、when_to_use（≤120 字）、side_effects（字符串数组，≤4）、
   preconditions（字符串数组，≤4）、returns（≤80 字，可空字符串）。
"""

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_MAX_TEXT = 200


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _string_list(value: Any, *, limit: int = 4) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:limit]:
        text = _text(item, 120)
        if text:
            items.append(text)
    return items


def parse_drafts(raw: str, known_ids: set[str]) -> list[dict[str, Any]]:
    """解析模型输出；未知 operation_id 与类型错误的条目直接丢弃。"""
    match = _JSON_ARRAY_RE.search(str(raw or ""))
    if not match:
        return []
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    drafts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        operation_id = _text(item.get("operation_id"), 120)
        if not operation_id or operation_id in seen or operation_id not in known_ids:
            continue
        when_to_use = _text(item.get("when_to_use"))
        if not when_to_use:
            continue
        seen.add(operation_id)
        drafts.append(
            {
                "operation_id": operation_id,
                "when_to_use": when_to_use,
                "side_effects": _string_list(item.get("side_effects")),
                "preconditions": _string_list(item.get("preconditions")),
                "returns": _text(item.get("returns"), 120),
            }
        )
    return drafts


def build_messages(batch: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = [
        {
            "operation_id": entry.get("operation_id"),
            "method": entry.get("method"),
            "path": entry.get("path"),
            "risk": entry.get("risk"),
            "domain": entry.get("domain"),
            "summary": entry.get("summary"),
        }
        for entry in batch
    ]
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def select_targets(
    operations: list[dict[str, Any]],
    *,
    limit: int,
    domains: set[str],
    skip_described: bool = True,
) -> list[dict[str, Any]]:
    order = {"read": 0, "write": 1, "danger": 2}
    targets = [
        entry
        for entry in operations
        if (not skip_described or not entry.get("described"))
        and (not domains or str(entry.get("domain")) in domains)
    ]
    targets.sort(key=lambda entry: (order.get(str(entry.get("risk")), 3), entry["operation_id"]))
    return targets[:limit] if limit > 0 else targets


def load_catalog(*, from_app: bool, catalog_json: str) -> dict[str, Any]:
    if catalog_json:
        return json.loads(Path(catalog_json).read_text(encoding="utf-8"))
    if not from_app:
        raise SystemExit("需要 --from-app 或 --catalog-json")
    from app.application.aiopen.catalog_builder import get_catalog
    from app.fastapi_app.factory import get_fastapi_app

    return get_catalog(get_fastapi_app())


async def generate(
    catalog: dict[str, Any],
    *,
    batch_size: int,
    limit: int,
    domains: set[str],
    profile: str,
    dry_run: bool,
) -> Path | None:
    operations = list(catalog.get("operations") or [])
    targets = select_targets(operations, limit=limit, domains=domains)
    if not targets:
        print("没有需要生成语义的 operation。")
        return None
    known_ids = {str(entry["operation_id"]) for entry in targets}
    batches = [targets[i : i + batch_size] for i in range(0, len(targets), batch_size)]
    if dry_run:
        print(json.dumps(build_messages(batches[0]), ensure_ascii=False, indent=2))
        print(f"\n待生成 {len(targets)} 条 / {len(batches)} 批（dry-run 未调用模型）")
        return None

    from app.infrastructure.llm.invoke import chat_completion_openai_format

    collected: dict[str, dict[str, Any]] = {}
    for index, batch in enumerate(batches, start=1):
        response = await chat_completion_openai_format(
            build_messages(batch),
            temperature=0.2,
            max_tokens=2000,
            profile=profile,
            reasoning_enabled=False,
        )
        content = ""
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices and isinstance(choices[0], dict):
                content = str((choices[0].get("message") or {}).get("content") or "")
        drafts = parse_drafts(content, known_ids)
        for draft in drafts:
            collected[draft["operation_id"]] = draft
        print(f"[{index}/{len(batches)}] 收到 {len(drafts)} 条语义草稿")

    if not collected:
        print("模型未返回可用草稿。")
        return None
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFT_DIR / f"draft-{datetime.now().strftime('%Y%m%d-%H%M%S')}.yaml"
    document = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": profile,
        "reviewed": False,
        "operations": [
            {**draft, "reviewed": False} for draft in sorted(collected.values(), key=lambda d: d["operation_id"])
        ],
    }
    path.write_text(
        "# AIOPEN 语义草稿：人工审核后移入 overlay/generated/*.yaml 才会生效。\n"
        + yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"草稿已写入 {path}（{len(collected)} 条）")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 AIOPEN 语义 overlay 草稿")
    parser.add_argument("--from-app", action="store_true", help="从当前应用构建目录")
    parser.add_argument("--catalog-json", default="", help="从目录 JSON 读取 operation")
    parser.add_argument("--limit", type=int, default=40, help="最多生成条数，0 表示不限")
    parser.add_argument("--batch-size", type=int, default=10, help="每批 operation 数")
    parser.add_argument("--domains", default="", help="限定业务域，逗号分隔")
    parser.add_argument("--profile", default="default", help="LLM profile")
    parser.add_argument("--dry-run", action="store_true", help="只打印首批提示词")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size 必须 ≥ 1")
    domains = {item.strip() for item in args.domains.split(",") if item.strip()}
    catalog = load_catalog(from_app=args.from_app, catalog_json=args.catalog_json)
    asyncio.run(
        generate(
            catalog,
            batch_size=args.batch_size,
            limit=args.limit,
            domains=domains,
            profile=args.profile,
            dry_run=args.dry_run,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
