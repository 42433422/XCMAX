"""将员工包 .py 脚本注册为 vibe-coding CodeSkill + ESkill 的全闭环工具。

调用方：
    ``attach_nl_workflow_to_employee_pack_dir`` 在创建画布工作流前先调用
    ``register_employee_pack_as_eskills``，得到一组真实可执行 ESkill，
    再通过 ``preset_eskill_nodes`` 注入 ``apply_nl_workflow_graph``。

结果形态：
    每个拆分步或整段员工脚本 → 1 条 ESkill + ESkillVersion，
    ``static_logic_json = {"type":"vibe_code","skill_id":<vibe_id>,...}``
    运行时经 eskill_runtime._execute_logic 走 vibe_eskill_adapter 真跑 Python。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modstore_server.models import ESkill, ESkillVersion, User

logger = logging.getLogger(__name__)

# LLM 拆分最多几步
_MAX_STEPS = 6


def get_vibe_coder(**kwargs: Any) -> Any:
    """Patchable shim around the shared vibe adapter."""
    from modstore_server.integrations.vibe_adapter import get_vibe_coder as _get_vibe_coder

    return _get_vibe_coder(**kwargs)


# ────────────────────────────────────────────────────────────────────────────
# 内部 helpers
# ────────────────────────────────────────────────────────────────────────────


def _sanitize_identifier(text: str, fallback: str = "skill") -> str:
    raw = re.sub(r"[^a-z0-9_]+", "_", (text or "").lower())
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw[:48] or fallback


def _dedupe_key(text: str) -> str:
    raw = re.sub(r"\s+", "", str(text or "").strip().lower())
    return raw or _sanitize_identifier(text, "skill")


def _extract_function_name(source: str) -> str:
    """从 Python 源码中提取第一个 def 名称；失败时返回 'execute'。"""
    m = re.search(r"^\s*def\s+([a-zA-Z_][a-zA-Z0-9_]*)", source, re.MULTILINE)
    return m.group(1) if m else "execute"


def _make_vibe_skill_id(name: str, suffix: str = "") -> str:
    base = _sanitize_identifier(name, "emp_skill")
    uid = uuid.uuid4().hex[:8]
    return f"{base}_{uid}" if not suffix else f"{base}_{suffix}_{uid}"


def _register_script_in_code_store(
    coder: Any,
    *,
    skill_id: str,
    name: str,
    domain: str,
    source_code: str,
) -> None:
    """把已有 Python 源码写入 vibe-coding code_store（不走 LLM）。"""
    try:
        from vibe_coding._internals import (  # type: ignore[import-not-found]
            CodeFunctionSignature,
            CodeSkill,
            CodeSkillVersion,
        )
    except ImportError as exc:
        raise RuntimeError(f"vibe-coding 未安装: {exc}") from exc

    fn_name = _extract_function_name(source_code)
    if coder.code_store.has_code_skill(skill_id):
        existing = coder.code_store.get_code_skill(skill_id)
        new_ver = CodeSkillVersion(
            version=existing.active_version + 1,
            source_code=source_code,
            function_name=fn_name,
            signature=CodeFunctionSignature(
                params=["**kwargs"], return_type="dict", required_params=[]
            ),
            domain_keywords=[],
            source_run_id=f"emp-{uuid.uuid4().hex[:8]}",
        )
        existing.add_version(new_ver, activate=True)
        existing.domain = domain
        coder.code_store.save_code_skill(existing)
    else:
        ver = CodeSkillVersion(
            version=1,
            source_code=source_code,
            function_name=fn_name,
            signature=CodeFunctionSignature(
                params=["**kwargs"], return_type="dict", required_params=[]
            ),
            domain_keywords=[],
            source_run_id=f"emp-{uuid.uuid4().hex[:8]}",
        )
        skill = CodeSkill(
            skill_id=skill_id,
            name=name,
            domain=domain,
            active_version=1,
            versions=[ver],
        )
        coder.code_store.save_code_skill(skill)


def _upsert_eskill(
    db: Session,
    user: User,
    *,
    name: str,
    domain: str,
    description: str,
    vibe_skill_id: str,
    source: str = "employee_pack",
) -> int:
    """创建（或复用同名）ESkill + ESkillVersion，返回 ESkill.id。"""
    existing = db.query(ESkill).filter(ESkill.user_id == user.id, ESkill.name == name).first()
    if existing:
        # bump version 指向新的 vibe skill_id
        prev_ver = existing.active_version
        new_ver_no = prev_ver + 1
        logic = {
            "type": "vibe_code",
            "skill_id": vibe_skill_id,
            "run_immediately": True,
            "output_var": "vibe_result",
            "source": source,
        }
        ver = ESkillVersion(
            eskill_id=existing.id,
            version=new_ver_no,
            static_logic_json=json.dumps(logic, ensure_ascii=False),
            trigger_policy_json=json.dumps({"on_error": True, "on_quality_below_threshold": True}),
            quality_gate_json=json.dumps({}),
            note=f"re-registered from {source}; vibe_skill_id={vibe_skill_id}",
        )
        db.add(ver)
        existing.active_version = new_ver_no
        existing.description = description or existing.description
        db.flush()
        return int(existing.id)

    logic = {
        "type": "vibe_code",
        "skill_id": vibe_skill_id,
        "run_immediately": True,
        "output_var": "vibe_result",
        "source": source,
    }
    skill = ESkill(
        user_id=user.id,
        name=name,
        domain=domain,
        description=description,
        active_version=1,
    )
    db.add(skill)
    db.flush()
    ver = ESkillVersion(
        eskill_id=skill.id,
        version=1,
        static_logic_json=json.dumps(logic, ensure_ascii=False),
        trigger_policy_json=json.dumps({"on_error": True, "on_quality_below_threshold": True}),
        quality_gate_json=json.dumps({}),
        note=f"registered from {source}; vibe_skill_id={vibe_skill_id}",
    )
    db.add(ver)
    db.flush()
    return int(skill.id)


# ────────────────────────────────────────────────────────────────────────────
# LLM 任务拆分
# ────────────────────────────────────────────────────────────────────────────

_SPLIT_SYSTEM_PROMPT = """\
你是一个 Python 工程师。用户给你一段员工功能描述（brief）和可选的功能摘要（panel_summary），
你需要把该员工的整体能力拆分为最多 {max_steps} 个独立 Python 技能步骤（Skill）。
每个 Skill 对应一个有明确输入/输出的 Python 函数。

输出**只要**一个合法 JSON 数组（不含 markdown 围栏，不含注释，不含解释），格式如下：
[
  {{
    "name": "步骤中文名（简洁，如「解析输入」「生成报告」）",
    "sub_brief": "用一句话描述这个函数的功能，供 vibe-coding 生成真实 Python 代码",
    "input_keys": ["key1", "key2"],
    "output_var": "result_变量名（英文下划线）",
    "domain": "此步骤业务领域（一句话）"
  }}
]

规则：
1. 步骤数 >= 1，<= {max_steps}
2. 步骤按执行顺序排列，前一步输出可作为后一步输入
3. 不得包含"启动""初始化"等纯占位步骤
4. 只输出 JSON 数组，不要其它内容
"""


def _strip_fence(text: str) -> str:
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, re.I | re.S)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


async def _llm_split_steps(
    brief: str,
    panel_summary: str,
    *,
    db: Session,
    user: User,
    provider: str,
    model: str,
) -> List[Dict[str, Any]]:
    """调 LLM 把员工 brief 拆成 N 步，返回 [{name,sub_brief,input_keys,output_var,domain}]。
    失败或解析错误返回空列表（由调用方 fallback 到单 Skill）。
    """
    from modstore_server.services.llm import chat_dispatch_via_session

    user_msg = f"员工功能描述（brief）：\n{brief}\n\n功能摘要（panel_summary，可为空）：\n{panel_summary or '（无）'}"
    sys_msg = _SPLIT_SYSTEM_PROMPT.format(max_steps=_MAX_STEPS)
    try:
        result = await chat_dispatch_via_session(
            db,
            user.id,
            provider,
            model,
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            max_tokens=1500,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("employee skill split LLM failed: %s", exc)
        return []

    if not result.get("ok"):
        logger.warning("employee skill split LLM error: %s", result.get("error"))
        return []

    raw = _strip_fence(str(result.get("content") or ""))
    try:
        steps = json.loads(raw)
    except json.JSONDecodeError:
        # 尝试找第一个 [ ... ]
        i, j = raw.find("["), raw.rfind("]")
        if i < 0 or j <= i:
            return []
        try:
            steps = json.loads(raw[i : j + 1])
        except json.JSONDecodeError:
            return []

    if not isinstance(steps, list):
        return []

    out: List[Dict[str, Any]] = []
    for item in steps[:_MAX_STEPS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        sub_brief = str(item.get("sub_brief") or "").strip()
        if not name or not sub_brief:
            continue
        out.append(
            {
                "name": name[:64],
                "sub_brief": sub_brief[:400],
                "input_keys": [str(k) for k in (item.get("input_keys") or [])[:8]],
                "output_var": _sanitize_identifier(str(item.get("output_var") or name), "result")[
                    :40
                ],
                "domain": str(item.get("domain") or "")[:200],
            }
        )
    return out


# ────────────────────────────────────────────────────────────────────────────
# 兜底模板脚本生成（不调 LLM）
# ────────────────────────────────────────────────────────────────────────────


def _fallback_step_script(step: Dict[str, Any], employee_fn: str) -> str:
    """为一个拆分步骤生成调用员工总函数的包装脚本（供 B 升级前保底）。"""
    fn = _sanitize_identifier(step["name"], "step") or "execute"
    out_var = step.get("output_var") or "result"
    input_keys = step.get("input_keys") or []
    args = ", ".join(f"{k}=kwargs.get({k!r})" for k in input_keys) if input_keys else "**kwargs"
    return f"""\
def {fn}(**kwargs):
    \"\"\"
    {step['sub_brief']}
    Auto-generated wrapper; will be upgraded by vibe-coding if LLM is available.
    \"\"\"
    try:
        from employees import {employee_fn}  # type: ignore
        raw = {employee_fn}({args})
    except Exception as exc:
        return {{"ok": False, "error": str(exc), "{out_var}": None}}
    return {{"ok": True, "{out_var}": raw}}
"""


def _fallback_whole_script(source: str, name: str, out_var: str = "result") -> str:
    """当整段员工脚本不分步时，生成包装入口。"""
    fn = _sanitize_identifier(name, "execute") or "execute"
    return source + f"\n\ndef {fn}_entry(**kwargs):\n    return {fn}(**kwargs)\n"


def _manifest_skill_steps(
    manifest: Dict[str, Any], brief: str, panel_summary: str
) -> List[Dict[str, Any]]:
    """Deterministically derive composable Skill steps from employee metadata."""
    raw_items: List[Dict[str, Any]] = []
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cognition = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    skills = cognition.get("skills") if isinstance(cognition.get("skills"), list) else []
    for item in skills:
        if isinstance(item, dict):
            raw_items.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "brief": str(item.get("brief") or item.get("description") or "").strip(),
                    "domain": str(item.get("domain") or "").strip(),
                }
            )
    metadata = v2.get("metadata") if isinstance(v2.get("metadata"), dict) else {}
    suggested = (
        metadata.get("suggested_skills")
        if isinstance(metadata.get("suggested_skills"), list)
        else []
    )
    for item in suggested:
        if isinstance(item, dict):
            raw_items.append(
                {
                    "name": str(item.get("name") or "").strip(),
                    "brief": str(item.get("brief") or item.get("description") or "").strip(),
                    "domain": str(item.get("domain") or "").strip(),
                }
            )
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    caps = emp.get("capabilities") if isinstance(emp.get("capabilities"), list) else []
    for cap in caps:
        cap_text = str(cap or "").strip()
        if cap_text:
            raw_items.append({"name": cap_text, "brief": cap_text, "domain": cap_text})

    seen: set[str] = set()
    steps: List[Dict[str, Any]] = []
    context = panel_summary or brief
    for item in raw_items:
        name = item["name"] or item["brief"]
        if not name:
            continue
        key = _dedupe_key(name)
        if key in seen:
            continue
        seen.add(key)
        desc = item["brief"] or name
        steps.append(
            {
                "name": name[:64],
                "sub_brief": (
                    f"实现员工能力「{name}」：{desc}。员工整体任务背景：{context[:500]}。"
                    "输入为 dict payload，返回 dict，包含处理结果、依据和错误信息。"
                )[:600],
                "input_keys": ["payload"],
                "output_var": _sanitize_identifier(name, "skill_result")[:40],
                "domain": item["domain"] or name,
            }
        )
        if len(steps) >= _MAX_STEPS:
            break
    return steps


def _brief_skill_steps(brief: str, panel_summary: str) -> List[Dict[str, Any]]:
    text = "。".join(x for x in [brief, panel_summary] if x)
    parts = [p.strip(" ，,;；。") for p in re.split(r"[；;。\n]+", text) if p.strip(" ，,;；。")]
    keywords = ("并", "和", "、", "，")
    if len(parts) <= 1 and any(k in text for k in keywords):
        parts = [
            p.strip(" ，,;；。") for p in re.split(r"[、，,]|并|和", text) if p.strip(" ，,;；。")
        ]
    steps: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for part in parts:
        if len(part) < 4:
            continue
        key = _dedupe_key(part)
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            {
                "name": part[:24],
                "sub_brief": (
                    f"实现员工子能力：{part}。输入为 dict payload，返回 dict，"
                    "包含处理结果、依据、错误信息和下一步建议。"
                )[:500],
                "input_keys": ["payload"],
                "output_var": _sanitize_identifier(part, "skill_result")[:40],
                "domain": part[:80],
            }
        )
        if len(steps) >= _MAX_STEPS:
            break
    return steps if len(steps) >= 2 else []


# ────────────────────────────────────────────────────────────────────────────
# 公开 API
# ────────────────────────────────────────────────────────────────────────────


async def register_employee_pack_as_eskills(
    db: Session,
    user: User,
    *,
    pack_dir: Path,
    brief: str,
    panel_summary: str = "",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status_hook: Optional[Callable[..., Any]] = None,
) -> List[Dict[str, Any]]:
    """扫描员工包 .py → 注册 vibe CodeSkill + ESkill，返回 eskill_specs 列表。

    每项格式：
        {"eskill_id": int, "vibe_skill_id": str, "name": str, "output_var": str}

    若 vibe-coding 未安装或脚本目录不存在，返回空列表（调用方按旧行为继续）。
    """
    try:
        from modstore_server.integrations.vibe_adapter import (
            VibeIntegrationError,
        )
    except ImportError:
        logger.warning("vibe_adapter 未导入，跳过员工 Skill 注册")
        return []

    emp_dir = pack_dir / "backend" / "employees"
    py_files = sorted(emp_dir.glob("*.py")) if emp_dir.is_dir() else []
    if not py_files:
        logger.info("员工包 %s 无 backend/employees/*.py，跳过 Skill 注册", pack_dir.name)
        return []

    if not provider or not model:
        logger.warning("register_employee_pack_as_eskills: 无 provider/model，跳过")
        return []

    try:
        coder = get_vibe_coder(session=db, user_id=user.id, provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 vibe coder 失败: %s", exc)
        return []

    if status_hook:
        try:
            r = status_hook("正在将员工脚本注册为真实 Skill…")
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass

    # ---------- 读取员工主脚本 ----------
    main_py = py_files[0]
    source_code = main_py.read_text(encoding="utf-8", errors="replace")
    employee_fn = _extract_function_name(source_code)
    pack_name = pack_dir.name
    manifest: Dict[str, Any] = {}
    mf_path = pack_dir / "manifest.json"
    if mf_path.is_file():
        try:
            raw_manifest = json.loads(mf_path.read_text(encoding="utf-8"))
            if isinstance(raw_manifest, dict):
                manifest = raw_manifest
        except (OSError, json.JSONDecodeError):
            manifest = {}

    # ---------- 第一步：尝试 LLM 拆分；失败时用 manifest/brief 确定性拆分 ----------
    steps = await _llm_split_steps(
        brief,
        panel_summary,
        db=db,
        user=user,
        provider=provider,
        model=model,
    )
    if not steps:
        steps = _manifest_skill_steps(manifest, brief, panel_summary)
    if not steps:
        steps = _brief_skill_steps(brief, panel_summary)

    eskill_specs: List[Dict[str, Any]] = []

    if steps:
        # ---- 多步模式 ----
        logger.info("员工 %s 拆分为 %d 步", pack_name, len(steps))
        for idx, step in enumerate(steps):
            step_name = f"{pack_name} · {step['name']}"
            vibe_sid = _make_vibe_skill_id(step_name)
            fallback_src = _fallback_step_script(step, employee_fn)

            # A. 兜底注册（不调 LLM，用模板脚本）
            try:
                _register_script_in_code_store(
                    coder,
                    skill_id=vibe_sid,
                    name=step_name,
                    domain=step.get("domain") or brief[:120],
                    source_code=fallback_src,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skill 兜底注册失败 step=%s: %s", step["name"], exc)
                continue

            # B. 升级：让 vibe-coding LLM 重新生成真实代码 + 沙箱
            vibe_sid_v2 = vibe_sid
            try:
                upgraded = coder.code(step["sub_brief"], mode="brief_first", skill_id=vibe_sid)
                vibe_sid_v2 = getattr(upgraded, "skill_id", vibe_sid)
                logger.info("Skill 升级成功 step=%s vibe_id=%s", step["name"], vibe_sid_v2)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Skill 升级失败（保留兜底）step=%s: %s", step["name"], exc)

            # 创建 / 更新 ESkill 行
            try:
                eskill_id = _upsert_eskill(
                    db,
                    user,
                    name=step_name[:128],
                    domain=step.get("domain") or pack_name,
                    description=step["sub_brief"][:400],
                    vibe_skill_id=vibe_sid_v2,
                    source=f"employee_pack:{pack_name}:step{idx}",
                )
                eskill_specs.append(
                    {
                        "eskill_id": eskill_id,
                        "vibe_skill_id": vibe_sid_v2,
                        "name": step_name,
                        "output_var": step.get("output_var") or f"step_{idx}_result",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ESkill 行创建失败 step=%s: %s", step["name"], exc)

    else:
        # ---- 单步模式（兜底）----
        logger.info("员工 %s 未成功拆分，使用整段脚本单 Skill", pack_name)
        skill_name = f"{pack_name} · 核心功能"
        vibe_sid = _make_vibe_skill_id(pack_name)

        # A. 兜底：直接写入 .py 原文
        try:
            _register_script_in_code_store(
                coder,
                skill_id=vibe_sid,
                name=skill_name,
                domain=brief[:120],
                source_code=source_code,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("单 Skill 兜底注册失败: %s", exc)
            return []

        # B. 升级
        vibe_sid_v2 = vibe_sid
        try:
            upgraded = coder.code(brief[:800], mode="brief_first", skill_id=vibe_sid)
            vibe_sid_v2 = getattr(upgraded, "skill_id", vibe_sid)
            logger.info("单 Skill 升级成功 vibe_id=%s", vibe_sid_v2)
        except Exception as exc:  # noqa: BLE001
            logger.warning("单 Skill 升级失败（保留兜底）: %s", exc)

        try:
            eskill_id = _upsert_eskill(
                db,
                user,
                name=skill_name[:128],
                domain=pack_name,
                description=brief[:400],
                vibe_skill_id=vibe_sid_v2,
                source=f"employee_pack:{pack_name}:whole",
            )
            eskill_specs.append(
                {
                    "eskill_id": eskill_id,
                    "vibe_skill_id": vibe_sid_v2,
                    "name": skill_name,
                    "output_var": "emp_result",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("单 Skill ESkill 行创建失败: %s", exc)

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("employee Skill 注册 commit 失败: %s", exc)
        db.rollback()
        return []

    if status_hook:
        n = len(eskill_specs)
        try:
            r = status_hook(f"已注册 {n} 个真脚本 Skill")
            if hasattr(r, "__await__"):
                await r
        except Exception:
            pass

    return eskill_specs
