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
if str(FHD_ROOT) not in sys.path:
    sys.path.insert(0, str(FHD_ROOT))

from app.utils.operational_errors import RECOVERABLE_ERRORS

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
6. 若 risk 为 danger（删除/批量/退款/发布类）：
   - when_to_use 必须点明不可逆或高影响的操作对象；
   - side_effects 必须写明影响范围（单条还是批量）以及是否不可逆；
   - preconditions 必须包含「已获得明确授权或审批」；
   - 不允许猜测业务阈值、金额上限或审批层级。
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


def _extract_json_objects(text: str) -> list[Any]:
    """从含推理文字或代码块的输出中逐个大括号提取 JSON 对象。"""
    objects: list[Any] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    objects.append(json.loads(text[start : index + 1]))
                except json.JSONDecodeError:
                    pass
                start = -1
    return objects


def _parse_payload(raw: str) -> list[Any]:
    match = _JSON_ARRAY_RE.search(raw)
    if match:
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            return payload
    return _extract_json_objects(raw)


def parse_drafts(raw: str, known_ids: set[str]) -> list[dict[str, Any]]:
    """解析模型输出；未知 operation_id 与类型错误的条目直接丢弃。"""
    payload = _parse_payload(str(raw or ""))
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
    risks: set[str] | None = None,
    only_ids: set[str] | None = None,
    skip_described: bool = True,
) -> list[dict[str, Any]]:
    order = {"read": 0, "write": 1, "danger": 2}
    targets = [
        entry
        for entry in operations
        if (not skip_described or not entry.get("described"))
        and (not domains or str(entry.get("domain")) in domains)
        and (not risks or str(entry.get("risk")) in risks)
        and (not only_ids or str(entry.get("operation_id")) in only_ids)
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
    risks: set[str],
    only_ids: set[str],
    profile: str,
    dry_run: bool,
    skip_described: bool = True,
) -> Path | None:
    operations = list(catalog.get("operations") or [])
    targets = select_targets(
        operations,
        limit=limit,
        domains=domains,
        risks=risks,
        only_ids=only_ids,
        skip_described=skip_described,
    )
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
        content = ""
        for attempt in (1, 2):
            try:
                response = await asyncio.wait_for(
                    chat_completion_openai_format(
                        build_messages(batch),
                        temperature=0.2,
                        max_tokens=6000,
                        profile=profile,
                        reasoning_enabled=False,
                    ),
                    timeout=120.0,
                )
            except RECOVERABLE_ERRORS as error:
                print(f"[{index}/{len(batches)}] 第 {attempt} 次请求失败：{type(error).__name__}")
                if attempt == 2:
                    break
                await asyncio.sleep(2.0)
                continue
            if isinstance(response, dict):
                choices = response.get("choices") or []
                if choices and isinstance(choices[0], dict):
                    content = str((choices[0].get("message") or {}).get("content") or "")
            if content:
                break
            print(f"[{index}/{len(batches)}] 模型返回空内容，重试")
            await asyncio.sleep(2.0)
        drafts = parse_drafts(content, known_ids)
        if content and not drafts:
            print(f"[{index}/{len(batches)}] 输出无法解析（{len(content)} 字符），已跳过")
        for draft in drafts:
            collected[draft["operation_id"]] = draft
        if drafts:
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
            {**draft, "reviewed": False}
            for draft in sorted(collected.values(), key=lambda d: d["operation_id"])
        ],
    }
    path.write_text(
        "# AIOPEN 语义草稿：人工审核后移入 overlay/generated/*.yaml 才会生效。\n"
        + yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"草稿已写入 {path}（{len(collected)} 条）")
    return path


def _resolve_ids(raw: str) -> set[str]:
    text = str(raw or "").strip()
    if not text:
        return set()
    candidate = Path(text)
    if candidate.is_file():
        lines = candidate.read_text(encoding="utf-8").splitlines()
        return {line.strip() for line in lines if line.strip()}
    return {item.strip() for item in text.split(",") if item.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 AIOPEN 语义 overlay 草稿")
    parser.add_argument("--from-app", action="store_true", help="从当前应用构建目录")
    parser.add_argument("--catalog-json", default="", help="从目录 JSON 读取 operation")
    parser.add_argument("--limit", type=int, default=40, help="最多生成条数，0 表示不限")
    parser.add_argument("--batch-size", type=int, default=10, help="每批 operation 数")
    parser.add_argument("--domains", default="", help="限定业务域，逗号分隔")
    parser.add_argument("--risk", default="", help="限定风险级别：read,write,danger（逗号分隔）")
    parser.add_argument(
        "--include-described", action="store_true", help="包含已有语义的 operation（用于重写）"
    )
    parser.add_argument(
        "--ids", default="", help="仅处理指定 operation_id（逗号分隔，或每行一个的文件路径）"
    )
    parser.add_argument("--profile", default="default", help="LLM profile")
    parser.add_argument("--dry-run", action="store_true", help="只打印首批提示词")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size 必须 ≥ 1")
    domains = {item.strip() for item in args.domains.split(",") if item.strip()}
    risks = {item.strip().lower() for item in args.risk.split(",") if item.strip()}
    only_ids = _resolve_ids(args.ids)
    catalog = load_catalog(from_app=args.from_app, catalog_json=args.catalog_json)
    asyncio.run(
        generate(
            catalog,
            batch_size=args.batch_size,
            limit=args.limit,
            domains=domains,
            risks=risks,
            only_ids=only_ids,
            profile=args.profile,
            dry_run=args.dry_run,
            skip_described=not args.include_described,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
