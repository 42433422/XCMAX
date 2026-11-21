"""One product boundary for every call into a configured browser MCP server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app.application.workflow.workflow_types import PlanGraph

MAX_BROWSER_STEPS = 32
MAX_BROWSER_DECISIONS = 12
MAX_BROWSER_SECONDS = 300
BROWSER_ACTIONS = frozenset(
    {
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_fill_form",
        "browser_select_option",
        "browser_press_key",
        "browser_wait_for",
        "browser_tabs",
        "browser_navigate_back",
        "browser_take_screenshot",
    }
)


def browser_action_allowed(action: str, params: dict[str, Any]) -> bool:
    if action not in BROWSER_ACTIONS:
        return False
    if any(str(key).startswith("_") or key in {"filename", "files", "file_path"} for key in params):
        return False
    if action == "browser_navigate" or "url" in params:
        try:
            url = urlsplit(str(params.get("url") or ""))
            return bool(
                url.scheme in {"http", "https"}
                and url.hostname
                and url.username is None
                and url.password is None
            )
        except ValueError:
            return False
    return True


def browser_execution_contract(plan: PlanGraph) -> dict[str, Any] | None:
    """Describe only a local, valid controller entry; plan claims never enable it."""
    if len(plan.nodes) != 1:
        return None
    seed = plan.nodes[0]
    if (
        not seed.tool_id.startswith("mcp__")
        or seed.action not in {"browser_navigate", "browser_snapshot"}
        or seed.depends_on
        or seed.next
        or seed.branches
        or not browser_action_allowed(seed.action, seed.params)
    ):
        return None
    from app.application.tools.mcp.registry import browser_server_config

    if browser_server_config(seed.tool_id) is None:
        return None
    return {
        "seed_node_id": seed.node_id,
        "tool_id": seed.tool_id,
        "actions": sorted(BROWSER_ACTIONS),
        "limits": {
            "steps": MAX_BROWSER_STEPS,
            "model_decisions": MAX_BROWSER_DECISIONS,
            "scheduling_deadline_seconds": MAX_BROWSER_SECONDS,
        },
        "semantics": (
            "这个本地认可的单节点是原 AgentRun 的浏览器控制入口，不是任务完成声明。"
            "执行层每次读取实际页面，再向同一图追加一个动作，重新经过原权限、审批和预算。"
            "用户授权的同一连续浏览器交互可作为一个控制目标映射到该入口；"
            "该目标仍必须完整保留原话中的对象、范围、否定、条件和先后顺序。"
        ),
        "verification_scope": (
            "终态仅证明 browser_wait_for 对非空文本成功，随后同会话新快照读回该文本；"
            "不能证明未读回的业务数据库、付款或外部投递成功。"
        ),
        "handoff": "登录、验证码、外部发送、付款和不支持的操作须暂停询问，不能宣称完成。",
        "review_requirement": (
            "必须独立判断整个原始目标是否能由这些动作及页面文本验证覆盖。"
            "不能遗漏不属于该连续浏览器交互的其他目标，不能因为存在控制入口就判通过；"
            "若目标超出能力，沿用原 violations/unsupported/clarification_question 规则。"
        ),
    }
