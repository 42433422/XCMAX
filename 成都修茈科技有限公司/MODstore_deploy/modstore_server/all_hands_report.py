# isort: skip_file
# ruff: noqa: E402, F401
"""数字管家「全员汇报」编排。

让在岗员工在数字管家的统一调度下，用同一个 manifest/RAG/research/metric 管线
完成三段汇报：

1. **架构 / 工作逻辑** — 从员工包 manifest（``employee_config_v2``）+ ``yuangon/``
   仓库节选反向叙述自己负责的文件结构、职责与协作依赖。
2. **遇到问题与解决方法** — 从 ``employee_execution_metrics`` 读最近失败/告警，
   写入 LLM prompt，让员工自己回顾并给出修复路径。
3. **联网 + GitHub 调研后的自我优化** — 复用 ``research_tools.build_research_context``
   抓 web + GitHub 公开材料，员工据此提出对自身文件/工作内容的优化建议，并
   声明与哪些其他岗位/manifest 字段联动。

这一管线是 :mod:`modstore_server.daily_employee_briefs` 的兄弟模块；区别：
- 调用方是数字管家而非定时邮件；
- 输出结构化 JSON（前端聊天/抽屉直接渲染）而非 HTML 邮件正文；
- 任务文案显式要求"联动其他岗位"，让汇报互相引用形成闭环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import desc

from modstore_server.daily_employee_briefs import (
    collect_yuangon_pack_excerpt,
    resolve_daily_brief_research_brief,
)
from modstore_server.duty_roster import all_planned_employee_ids, yuangon_area_for_pkg
from modstore_server.employee_executor import execute_employee_task
from modstore_server.employee_runtime import load_employee_pack
from modstore_server.models import (
    CatalogItem,
    EmployeeExecutionMetric,
    get_session_factory,
)
from modstore_server.research_tools import build_research_context
from modstore_server.services.llm import resolve_platform_bench_llm

# 单次员工大会可调度人数上限（覆盖 duty_roster 编制 52 + 余量；仍受 LLM bench 配额约束）
MAX_ALL_HANDS_EMPLOYEES = 128


from modstore_server.all_hands_report_part01 import (
    clamp_all_hands_max_employees as clamp_all_hands_max_employees,
    all_hands_employee_timeout_sec as all_hands_employee_timeout_sec,
)

logger = logging.getLogger(__name__)

AllHandsProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


# ─── 任务文案：固定结构，便于前端与 ``daily_employee_briefs`` 同步迭代 ──────────
ALL_HANDS_QA_TASK_TEMPLATE = """你是 MODstore 在岗 AI 员工 ``{employee_id}``。
现在数字管家在「员工大会」上转交一个用户提出的问题，请只用你这个岗位的视角回答。

**用户问题**（必须正面回应，不要绕开）：
> {user_question}

请基于 input 中的 ``manifest_signals`` / ``role_context`` / ``yuangon_employee_meta`` /
``yuangon_pack_excerpt`` / ``recent_failures`` /
``research_context``（如有）作答；不得编造任何不在 manifest / 节选 / 流水中的事实。

按以下固定结构输出 **简体中文 Markdown**（**不要修改二级标题措辞**）：

## 一、是否与我的岗位相关
- 在「相关 / 部分相关 / 不相关」三选一，并简述判断依据；
- 若不相关：仍要在第二节给出「我所知最相近的岗位是谁」（点 1-2 个 ``other_employees`` 中的 pkg_id）。

## 二、岗位视角下的回答
- 用 3-6 个 bullet 直接回答用户问题；
- 每条尽量绑定一项可核验的根据：``manifest_signals.handlers / depends_on / behavior_rules``、
  ``yuangon_pack_excerpt`` 中的相对路径、或 ``recent_failures`` 中的具体记录；
- 任何不能落到上述根据的推断，必须明确写「这是推断 / 待确认」。

## 三、给数字管家的协作建议（可选）
- 0-3 条；每条形如 ``owner: <pkg_id 或 self>`` + 一句话执行项；
- 优先点名 ``other_employees`` 中能补全本问题的同事（如本岗位资料不足）。

## 四、引用
- 列出本次回答用到的事实根据：每条形如 ``- <来源>: <key 或路径>``；
- 没有可引用根据时写 ``- 无可引用根据，回答仅来自 manifest 字段。``，不得空白。
"""


ALL_HANDS_TASK_TEMPLATE = """你是 MODstore 在岗 AI 员工 ``{employee_id}``。
现在数字管家正在召集"全员汇报"，请基于 input 中的 ``research_context``、
``yuangon_pack_excerpt``、``recent_failures``、``employee_label`` 与 manifest，
按下面的固定结构产出 **简体中文 Markdown**（**不要改二级标题措辞**）：

在输出前先判断输入可用性；即使有字段为空，也必须完整输出四个章节，不得拒答：
- ``yuangon_pack_excerpt`` 为空：第一节改为依据 ``manifest_signals`` + ``yuangon_area`` 写职责边界，
  并明确写出「仓库节选缺失，待同步 yuangon 目录」；不得编造相对路径；**Mermaid 架构图仍须输出**，
  仅画 manifest / ``yuangon_area`` 可支撑的最小边界，未知路径用「待同步 yuangon」类节点标注，不得臆造目录名。
- ``recent_failures`` 为空：第二节改为依据 ``manifest_signals.behavior_rules``（可辅以 persona/skills）
  写 1-3 条潜在风险与预防动作，并明确写出「近期失败流水为空」；不得编造报错记录。
- ``research_context`` 为空：第三节仍需给 2-3 条可执行建议，依据只能写 manifest 字段或
  「待联网检索验证（当前 research_context 为空）」；不得伪造网页链接或 GitHub 仓库信息。

## 一、文件与工作逻辑
- 用 **3-5 条** 描述你负责的目录/文件、对外接口、内部数据流；
- ``yuangon_pack_excerpt`` 非空时尽量引用其中相对路径；为空时引用 manifest 字段名；
- 末尾用一行总结"对外提供什么 / 依赖谁"。
- 在上述 bullet 之后，**必须**插入一段 **Mermaid** 架构图：使用 `` ```mermaid `` 代码围栏，推荐 ``flowchart LR`` 或 ``flowchart TB``，
  画出与本岗相关的目录/系统边界、数据或审核流、**CI / 审批边界**（若有：如仅提交审核状态、不直连生产库等事实）以及对外服务与上游依赖；
  图中节点与边须与上文文字及 ``yuangon_pack_excerpt`` / manifest 一致，不得臆造未出现的仓库路径或系统名；信息不足时在图注或节点标签中写「待确认 / 待同步 yuangon」。

## 二、最近遇到的问题与解决方法
- 优先解读 ``recent_failures``（``employee_execution_metrics`` 中近期失败任务）；
  若该数组为空，则结合 manifest ``behavior_rules`` / ``persona`` / ``skills`` 写"潜在风险点"；
- 每条："**问题** → **诊断** → **解决路径**"三段式，列 1-3 条。
- 不得编造未出现在 ``recent_failures`` / 节选中的故障。

## 三、上网调研后的自我优化建议
- 基于 ``research_context``（公开网页 + GitHub 仓库摘要）+ 自己的 manifest，
  提出 **2-3 条** 可立即落地的改动；
- 每条："**建议** → **依据**（节选路径 或 research_context 中的具体来源链接 / repo）
  → **联动**（点名 1-2 个其他在岗员工 ID 与他们要做的协作项）"。
- ``research_context`` 为空时，依据写 manifest 字段名或「待联网检索验证」。
- 联动至少要点到一个 ``other_employees`` 列表中的 pkg_id，方便数字管家串起来。

## 四、给数字管家的待办（可执行）
- 0-3 条机器可读的待办；每条形如：
  - ``- task: <一句话>``
  - ``  owner: <pkg_id 或 self>``
  - ``  hint: <可贴到 ai-store 搜索 / 工作流 brief 的关键词>``

禁止编造 ``research_context`` / ``yuangon_pack_excerpt`` / ``recent_failures`` 中均未出现的版本号、文件名、内部政策。
字段为空时请明确写「待确认 / 待同步」，不要输出「无法生成完整汇报」。
当 input 含 ``all_hands_standby: true`` 时：制作车间流水线岗位（intent/artifact/workflow 等）**只汇报职责与待机条件**，
不要声称已执行需要上游产物（员工包、workflow_id、产物路径）的流水线步骤；用 manifest 说明「就绪，等待上游输入」即可。
"""

# 制作车间流水线岗位：日常 cognition 会按 manifest 输出 operational JSON（含「输入不足」告警），
# 与员工大会四段 Markdown 冲突；待机汇报改走 bench 直出。

_ALL_HANDS_STANDBY_SYSTEM = """你是 MODstore 在岗 AI 员工，正在参加数字管家召集的「员工大会」。
当前为**待机汇总模式**（非制作车间流水线执行、非工作台单次任务）。

硬性要求：
- 只输出 **简体中文 Markdown**，严格按用户消息中的四段标题结构作答；**禁止**输出 JSON、禁止 ``warnings`` / ``status`` 字段。
- 缺上游产物、缺 workflow_id、缺员工包路径在待机模式下**属于正常**，不得写「输入不足」类流水线报错。
- 用 manifest / depends_on / handlers 说明本岗职责、上下游协作与「就绪，等待上游输入」即可。
- 不得编造 research_context / yuangon_pack_excerpt / recent_failures 中未出现的路径或版本号。"""


from modstore_server.all_hands_report_part02 import (
    _craft_workshop_pkg_ids as _craft_workshop_pkg_ids,
)

CRAFT_WORKSHOP_STANDBY_IDS = _craft_workshop_pkg_ids()


from modstore_server.all_hands_report_part03 import (
    _should_standby_manifest_report as _should_standby_manifest_report,
    _craft_pipeline_standby_context as _craft_pipeline_standby_context,
    _is_standby_pipeline_json_noise as _is_standby_pipeline_json_noise,
    _coerce_standby_excerpt as _coerce_standby_excerpt,
    _resolve_employee_pairs as _resolve_employee_pairs,
    _recent_failures as _recent_failures,
    _load_yuangon_employee_meta as _load_yuangon_employee_meta,
    _snapshot_pending_change_requests as _snapshot_pending_change_requests,
    _snapshot_employee_cron_overview as _snapshot_employee_cron_overview,
    _all_hands_role_context as _all_hands_role_context,
    _manifest_signals as _manifest_signals,
    _standby_manifest_report_via_bench as _standby_manifest_report_via_bench,
    _report_one_employee as _report_one_employee,
)

# ─── 综合答复（数字管家把 19 名员工的回答合并） ──────────────────────────────


_SYNTHESIZE_SYSTEM_PROMPT = """你是 MODstore 的「数字管家」。
管理员把同一个问题转发给在岗的多名员工，并把每位员工以自己岗位视角写的答复
作为输入交给你。你需要：

1) 用一句话给出最终答复（是 / 否 / 部分 / 暂不确定）；
2) 用 3-6 个 bullet 综合所有员工的事实（必须**点名引用** ``employee_id``）；
3) 如果不同员工存在分歧，单独写一节「分歧」并标出谁说什么；
4) 给出 0-3 条对管理员的下一步建议（每条 ``owner: <pkg_id 或 self>`` 形式）。

硬性要求：
- 仅基于输入的员工答复内容，不得编造任何员工没说过的事实。
- 引用员工时使用 ``[pkg_id]`` 这种方括号形式，便于前端转链接。
- 整体输出 **简体中文 Markdown**。
"""


from modstore_server.all_hands_report_part04 import (
    _employee_answer_excerpt as _employee_answer_excerpt,
    synthesize_all_hands_answer as synthesize_all_hands_answer,
)

_MEETING_MINUTES_SYSTEM_PROMPT = """你是 MODstore 的数字管家秘书，根据「员工大会」上各 AI 员工的汇报节选（及可能有的综合答复），写一份给**管理员**看的会议摘要。

写作风格（说人话）：
- 用**大白话、短句**，像跟同事口头汇报；避免堆砌英文缩写、handler 名、JSON 字段名。
- 技术细节只保留管理员能决策的信息（谁负责、卡在哪、下一步做什么）。
- 制作车间岗位在**待机汇总**时写「流水线就绪、等待工单」即可；不要把「缺上游输入」当成故障反复写。

硬性要求：
- **仅基于**输入中出现的汇报与综合答复归纳；不得编造输入中不存在的事实。
- 忽略节选里残留的 operational JSON、「输入不足」类流水线告警（待机模式下属正常）。
- 输出用 **简体中文**，且**严格按下面结构**（第一行必须是「会议摘要」四字，随后「一、」到「五、」标题措辞不可改）：

会议摘要
一、会议主题：……
二、现状（各岗在做什么 / 待机情况）：……
三、问题与风险
- ……
四、下一步
- ……
五、其他说明：……

- 「三」「四」下用 Markdown 无序列表，以 `- ` 开头；若无问题或可写「- 无」。
- 「五」可写「无」或一句补充。
- 不要添加与上述结构无关的前言、后记或思维链。"""


from modstore_server.all_hands_report_part05 import (
    synthesize_meeting_minutes as synthesize_meeting_minutes,
    build_all_hands_report as build_all_hands_report,
    all_hands_concurrency_default as all_hands_concurrency_default,
)
