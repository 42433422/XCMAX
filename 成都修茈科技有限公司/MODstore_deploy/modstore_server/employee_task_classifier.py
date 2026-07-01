"""任务分类器（10 项成熟度第 3 项「会判断任务」）。

不是收到一句话就乱跑，要能判断：这是 bug、需求、运维、测试、发布、安全、
文档，还是需要转交别人。

设计：纯关键词规则，不调 LLM（避免成本/延迟）。
  - 输入：task 文本（中文为主）
  - 输出：{category, confidence, reason, matched_keywords, suggested_target}
  - category ∈ bug | feature | ops | test | release | security | doc | handoff | unknown

挂载点：employee_executor 在 perception 后、cognition 前调用，
把结果写到 perceived["task_classification"] 让 LLM 也能感知到任务类型。
human_report 在「发现什么」段反映。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


# 关键词表：按优先级从高到低排序（先匹配的胜出）
# 每项：(category, [关键词列表], suggested_target_prefix)
# suggested_target_prefix 是建议目标员工的 employee_id 前缀（不是硬指派）
_CATEGORY_RULES: List[Tuple[str, List[str], str]] = [
    (
        "security",
        [
            "安全",
            "漏洞",
            "越权",
            "sql注入",
            "xss",
            "csrf",
            "rce",
            "密钥泄露",
            "权限绕过",
            "敏感数据",
            "加密",
            "证书过期",
            "鉴权",
            "认证失败",
            "security",
            "vulnerability",
            "cve",
            "exploit",
            "leak",
            "secret",
        ],
        "security-",
    ),
    (
        "bug",
        [
            "bug",
            "缺陷",
            "报错",
            "错误",
            "异常",
            "崩溃",
            "crash",
            "故障",
            "排错",
            "排查问题",
            "修复",
            "fix",
            "broken",
            "失败",
            "不工作",
            "无法",
            "无效",
            "出错",
            "exception",
            "traceback",
            "error",
        ],
        "",
    ),
    (
        "release",
        [
            "发布",
            "上线",
            "deploy",
            "deployment",
            "rollback",
            "回滚",
            "上线版本",
            "release",
            "ship",
            "发版",
            "灰度",
            "blue-green",
        ],
        "release-",
    ),
    (
        "ops",
        [
            "运维",
            "ops",
            "部署",
            "重启",
            "服务挂了",
            "磁盘",
            "cpu",
            "内存",
            "监控",
            "告警",
            "alert",
            "incident",
            "线上",
            "线上服务",
            "健康检查",
            "host probe",
            "机器",
            "节点",
            "k8s",
            "pod",
            "容器",
        ],
        "host-",
    ),
    (
        "test",
        [
            "测试",
            "test",
            "回归",
            "单测",
            "unit test",
            "集成测试",
            "e2e",
            "覆盖率",
            "coverage",
            "测试用例",
            "test case",
            "qa",
            "质检",
            "验证",
            "verify",
            "断言",
            "assert",
        ],
        "qa-",
    ),
    (
        "doc",
        [
            "文档",
            "doc",
            "documentation",
            "readme",
            "使用说明",
            "操作手册",
            "runbook",
            "knowledge",
            "知识库",
            "wiki",
            "整理文档",
            "更新文档",
        ],
        "doc-",
    ),
    (
        "feature",
        [
            "需求",
            "feature",
            "新功能",
            "实现",
            "开发",
            "增加",
            "添加",
            "支持",
            "改造",
            "重构",
            "refactor",
            "enhancement",
        ],
        "",
    ),
    (
        "handoff",
        [
            "转交",
            "转给",
            "移交",
            "delegate",
            "handoff",
            "不归我",
            "不是我",
            "交给",
            "转给同事",
            "@",
        ],
        "",
    ),
]


# 任务文本过短直接归 unknown，避免误判
_MIN_TEXT_LEN = 4


def classify_task(task_text: str) -> Dict[str, Any]:
    """给 task 文本分类。

    返回：
      {
        "category": str,             # bug|feature|ops|test|release|security|doc|handoff|unknown
        "confidence": float,         # 0.0-1.0，命中关键词数越多越高
        "reason": str,               # 为什么这么分类（人话）
        "matched_keywords": [...],   # 命中的关键词列表
        "suggested_target_prefix": str,  # 建议目标员工的 employee_id 前缀
        "should_handoff": bool,      # 是否建议转交（category=handoff 或匹配到 @员工）
      }
    """
    text = str(task_text or "").strip().lower()
    if not text or len(text) < _MIN_TEXT_LEN:
        return {
            "category": "unknown",
            "confidence": 0.0,
            "reason": "任务文本过短或为空，无法判断类型",
            "matched_keywords": [],
            "suggested_target_prefix": "",
            "should_handoff": False,
        }

    matched: List[Tuple[str, List[str], str]] = []
    for cat, kws, prefix in _CATEGORY_RULES:
        hits = [kw for kw in kws if kw in text]
        if hits:
            matched.append((cat, hits, prefix))

    if not matched:
        return {
            "category": "unknown",
            "confidence": 0.1,
            "reason": "未命中任何分类关键词，可能是泛化任务或纯决策",
            "matched_keywords": [],
            "suggested_target_prefix": "",
            "should_handoff": False,
        }

    # 取命中关键词最多的类别胜出（同数时按 _CATEGORY_RULES 顺序优先）。
    # _CATEGORY_RULES 已按优先级排序（security > bug > release > ops > test > doc > feature > handoff）。
    matched.sort(key=lambda x: (-len(x[1]),))
    cat_first, kws_first, prefix_first = matched[0]
    # 若 handoff 命中关键词，建议转交
    handoff_match = next((m for m in matched if m[0] == "handoff"), None)
    should_handoff = handoff_match is not None and len(handoff_match[1]) >= 1

    # 置信度：命中数 / 5（封顶 1.0）
    confidence = min(1.0, len(kws_first) / 5.0)

    # 生成人话 reason
    if cat_first == "handoff":
        reason = f"任务提到转交关键词（{', '.join(kws_first[:3])}），建议转交"
    elif should_handoff:
        reason = (
            f"判断为 {cat_first}（命中：{', '.join(kws_first[:3])}），但同时也提到转交，可考虑转交"
        )
    else:
        reason = f"判断为 {cat_first}（命中关键词：{', '.join(kws_first[:3])}）"

    return {
        "category": cat_first,
        "confidence": round(confidence, 2),
        "reason": reason,
        "matched_keywords": kws_first[:8],
        "suggested_target_prefix": prefix_first,
        "should_handoff": should_handoff,
    }


def enrich_perception_with_classification(
    *,
    employee_id: str,
    task: str,
    perceived: Dict[str, Any],
) -> None:
    """把分类结果注入到 perceived["task_classification"]，供 LLM cognition 感知。

    设计为就地修改 perceived dict（与 perception_enricher.enrich_perception 一致）。
    """
    if not isinstance(perceived, dict):
        return
    try:
        classification = classify_task(task)
        # 放到 normalized_input 里，让 _cognition_real 能在 user message 看到
        ni = perceived.get("normalized_input")
        if not isinstance(ni, dict):
            ni = {}
            perceived["normalized_input"] = ni
        ni["_task_classification"] = classification
    except Exception as exc:  # noqa: BLE001
        logger.debug("task_classifier enrich failed employee_id=%s err=%s", employee_id, exc)


__all__ = ["classify_task", "enrich_perception_with_classification"]
