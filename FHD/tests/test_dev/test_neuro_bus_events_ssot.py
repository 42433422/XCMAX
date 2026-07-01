"""neuro-bus-events SSOT 派生守卫:三流事件契约一致 + 源 schema 合法 + 交叉校验通过。

自包含(subprocess,不 import app),不触发 app.services 的预存循环导入。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
SCRIPT = FHD / "scripts" / "dev" / "neuro_bus_events_ssot.py"
SOURCE = FHD / "config" / "neuro_bus_events.yaml"
DERIVED_PY = FHD / "app" / "neuro_bus" / "event_types_generated.py"
DERIVED_TS = FHD / "frontend" / "src" / "types" / "agentRunEvents.generated.ts"
OPENAPI = FHD / "contracts" / "openapi.json"


def _run_check() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "check"],
        cwd=str(FHD),
        capture_output=True,
        text=True,
    )


def test_check_returns_zero_when_in_sync():
    """派生产物与 neuro_bus_events.yaml 一致;漂移则失败并提示重生成。"""
    result = _run_check()
    assert result.returncode == 0, (
        "neuro-bus-events 派生漂移,请运行 "
        "python scripts/dev/neuro_bus_events_ssot.py generate --apply\n"
        + result.stdout
        + result.stderr
    )


def test_generate_is_idempotent():
    """连跑两次 generate --apply 后 check 仍为 0(字节确定性,无抖动)。"""
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(SCRIPT), "generate", "--apply"],
            cwd=str(FHD),
            capture_output=True,
            text=True,
        )
    result = _run_check()
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_fails_when_drift_introduced(tmp_path):
    """改动生成文件一字节,check 必须 exit 1。"""
    original = DERIVED_PY.read_text(encoding="utf-8")
    try:
        # 在文件末尾追加一个空格制造漂移
        DERIVED_PY.write_text(original + " ", encoding="utf-8")
        result = _run_check()
        assert result.returncode == 1, (
            f"期望 exit 1(漂移检测),实际 exit {result.returncode}\n"
            + result.stdout
            + result.stderr
        )
    finally:
        DERIVED_PY.write_text(original, encoding="utf-8")


def test_all_dataclass_event_type_defaults_exist_in_ssot():
    """扫 app/neuro_bus/events/*.py 的 event_type: str = "..." 默认值,
    assert 全部在 ALL_EVENT_TYPES(由 check 命令的交叉校验 #2 守护)。
    """
    import re

    pattern = re.compile(r'event_type:\s*str\s*=\s*["\']([^"\']+)["\']')
    found: set[str] = set()
    events_dir = FHD / "app" / "neuro_bus" / "events"
    for path in sorted(events_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            found.add(match.group(1))

    assert found, "未扫描到任何 dataclass event_type 默认值 — 扫描器或测试可能失效"
    # check 命令内部执行交叉校验,这里复用它
    result = _run_check()
    assert result.returncode == 0, (
        "check 交叉校验失败,可能有 dataclass 默认值未登记在 SSOT:\n"
        + result.stderr
    )


def test_all_orchestrator_run_add_event_strings_exist_in_ssot():
    """扫 orchestrator.py + chat_trace.py + artifact_ingestion.py 的 add_event /
    event_type=billing_event= 字符串,assert 全部在 ALL_EVENT_TYPES。
    """
    result = _run_check()
    assert result.returncode == 0, (
        "check 交叉校验失败,可能有 orchestrator 字符串未登记在 SSOT:\n"
        + result.stderr
    )


def test_frontend_useAgentRunEvents_strings_exist_in_ssot():
    """扫 useAgentRunEvents.ts 的 dot.notation 字符串字面量,
    assert 全部在 agent_run 流(用 subprocess 读派生文件,避免 app import cycle)。
    """
    import re

    composable = FHD / "frontend" / "src" / "composables" / "useAgentRunEvents.ts"
    text = composable.read_text(encoding="utf-8")
    # 提取所有 dot.notation 字符串字面量
    pattern = re.compile(r"""['"]([a-z]+\.[a-z_]+)['"]""")
    candidates = {match.group(1) for match in pattern.finditer(text)}
    # 过滤明显不是事件类型的字符串(如 'success' / 'failed' 不含点)
    agent_run_prefixes = {
        "run", "planner", "step", "tool", "llm", "billing", "budget",
        "observation", "artifact", "rag", "memory", "dataset",
    }
    event_strings = {
        s for s in candidates
        if "." in s and s.split(".")[0] in agent_run_prefixes
    }

    assert event_strings, "未扫描到任何 agent_run 事件字符串 — 扫描器或测试可能失效"

    # 从生成的派生文件直接提取 AGENT_RUN_EVENT_TYPES(避免 import app.neuro_bus 触发 3.9 语法错误)
    derived_text = DERIVED_PY.read_text(encoding="utf-8")
    ar_block_match = re.search(
        r'AGENT_RUN_EVENT_TYPES: frozenset\[str\] = frozenset\(\{(.*?)\}\)',
        derived_text,
        re.DOTALL,
    )
    assert ar_block_match, "未在派生文件中找到 AGENT_RUN_EVENT_TYPES frozenset"
    ar_types = set(re.findall(r'"([^"]+)"', ar_block_match.group(1)))

    missing = event_strings - ar_types
    assert not missing, (
        f"useAgentRunEvents.ts 中以下字符串未登记在 agent_run 流: {sorted(missing)}"
    )
