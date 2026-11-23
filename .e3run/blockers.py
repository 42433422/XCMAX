"""Emit UNRATED evidence records for domains that cannot reach E3 in this environment.

Each record states the concrete, observed blocker instead of a score. No assertion is
invented and no pass is claimed.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

HARNESS = Path("/Users/Shared/XCMAX/.e3run/harness.py")
spec = importlib.util.spec_from_file_location("e3_harness", HARNESS)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

ROOT = Path("/Users/Shared/XCMAX")


def count(path: str) -> int:
    p = ROOT / path
    if not p.exists():
        return -1
    return sum(1 for _ in p.rglob("*") if _.is_file())


def have(cmd: str) -> str:
    return subprocess.run(["which", cmd], capture_output=True, text=True).stdout.strip() or "MISSING"


MODEL_BLOCK = (
    "本机无可用模型凭证：04 域真实请求 POST /api/templates/reviewed-excel/preview 返回 "
    "model_configuration_error（见 04.json），说明 require_model_session 无法建立真实模型会话"
)

RECORDS = {
    "03": {
        "title": "Agent 编排与审批",
        "task": "真实模型驱动多 Agent 任务编排 + 审批闸门 + 中断恢复",
        "blockers": [
            MODEL_BLOCK,
            "本域核心任务必须由真实模型产生工具调用与计划；用 Mock/无模型无法构成 E3 证据",
        ],
        "probes": {"scope": "FHD/app/application/agent_orchestrator", "files": count("FHD/app/application/agent_orchestrator")},
        "additional_unknowns": ["未执行任何带模型的多 Agent 编排任务"],
    },
    "05": {
        "title": "AI 意图与工具路由",
        "task": "≥100 个独立留出意图任务 × 3 次重复，记录模型版本与预算，含负向/恢复",
        "blockers": [
            MODEL_BLOCK,
            "协议要求至少 100 个独立留出任务并重复 3 次；本机无模型会话，无法产生示例外路由结果",
        ],
        "probes": {"scope": "FHD/app/application/chat_business_safety_core.py",
                   "files": count("FHD/app/application/chat_business_safety_core.py")},
        "additional_unknowns": ["未构造留出任务集，样本量 0/100"],
    },
    "08": {
        "title": "桌面壳与更新恢复",
        "task": "Electron 壳真实启动 → 后端生命周期 → 安装包升级 → 失败回退",
        "blockers": [
            "需要 GUI 会话与 electron-builder 打包产物（electron-builder.yml + 签名安装包）；"
            "本环境无显示器/签名证书，无法执行真实安装与回退",
        ],
        "probes": {
            "desktop_dist_compiled": (ROOT / "FHD/desktop/dist").is_dir(),
            "electron_dependency_present": (ROOT / "FHD/desktop/node_modules/electron").is_dir(),
            "pack_script": "electron-builder --config electron-builder.yml",
            "node": have("node"),
        },
        "additional_unknowns": ["未执行打包、安装、签名校验与回退流程"],
    },
    "09": {
        "title": "FHD 前端与用户任务",
        "task": "构建前端 → 真实浏览器完成下单/库存/财务等用户任务 → 网络故障恢复",
        "blockers": [
            "前端未构建：FHD/frontend 无 dist 产物（仅源码 + vite 配置），"
            "且本轮未接入浏览器自动化，无法产生真实 UI 任务证据",
        ],
        "probes": {"frontend_files": count("FHD/frontend"), "frontend_dist": (ROOT / "FHD/frontend/dist").exists(),
                   "build_script": "vite build"},
        "additional_unknowns": ["未构建前端，未执行任何浏览器用户任务"],
    },
    "10": {
        "title": "商城前端与工作流 UI",
        "task": "商城前端构建 → 真实浏览器走通检索/购买/交付工作流 → 失败恢复",
        "blockers": [
            "需要商城前端独立构建与市场后端联调（真实套餐/账号/支付环境）；"
            "本环境无市场凭证，未构建前端",
        ],
        "probes": {"market_files": count("成都修茈科技有限公司/MODstore_deploy/market")},
        "additional_unknowns": ["未执行商城 UI 工作流"],
    },
    "11": {
        "title": "商城交易与交付后端",
        "task": "真实订单/支付回调/交付授权闭环 + 重复支付与失败补偿",
        "blockers": [
            "modstore_server 为独立 uvicorn 服务，需独立部署配置、数据库与市场账号密钥；"
            "本环境未部署该服务，无回调与支付凭证，无法执行交易闭环",
        ],
        "probes": {"modstore_server_files": count("成都修茈科技有限公司/MODstore_deploy/modstore_server"),
                   "entry": "uvicorn.run (__main__.py)"},
        "additional_unknowns": ["未启动 modstore_server，未执行订单/支付/交付任务"],
    },
    "13": {
        "title": "Java 支付服务",
        "task": "Java 服务启动 + 支付宝沙箱下单/回调/退款 + 幂等与重放",
        "blockers": [
            "application.yml 中 alipay.app-id / private-key / public-key 均为空环境变量默认值，"
            "无支付宝沙箱凭证；无运行中的支付服务，无法完成真实扣款与回调验证",
        ],
        "probes": {"java": have("java"), "pom": (ROOT / "成都修茈科技有限公司/MODstore_deploy/java_payment_service/pom.xml").is_file(),
                   "alipay_env_defaults_empty": True},
        "additional_unknowns": ["未编译、未启动支付服务，未发起任何支付"],
    },
    "14": {
        "title": "Flutter 移动端",
        "task": "真机/模拟器安装 App → 登录 → 核心业务 → 断网/升级恢复",
        "blockers": [
            "本机缺少 flutter 与 adb，且无连接设备/模拟器，无法构建与真机验证",
        ],
        "probes": {"flutter": have("flutter"), "adb": have("adb"),
                   "mobile_files": count("FHD/mobile-flutter-poc")},
        "additional_unknowns": ["未构建移动端产物，未执行真机任务"],
    },
    "16": {
        "title": "Vibe 编码与沙箱",
        "task": "真实模型由自然语言生成代码 → 沙箱执行校验 → 自愈重试",
        "blockers": [
            MODEL_BLOCK,
            "本包提供了 MockLLM 夹具；但用模拟 LLM 生成的代码不能作为本域 E3 证据"
            "（协议明确禁止以模拟 LLM 替代 E3）",
        ],
        "probes": {"vibe_files": count("成都修茈科技有限公司/vibe-coding"),
                   "mock_llm_available": True, "real_model": "unavailable"},
        "additional_unknowns": ["沙箱运行时本身可真实执行代码，但缺少真实模型侧的端到端任务"],
    },
    "17": {
        "title": "客来来独立子系统",
        "task": "客来来子系统端到端会话与工单闭环",
        "blockers": [
            "scope 目录 market/src/domain/客来来 文件数为 0，产品代码不在本工作区，无任何可执行对象",
        ],
        "probes": {"kellai_files": count("成都修茈科技有限公司/MODstore_deploy/market/src/domain/客来来")},
        "additional_unknowns": ["代码缺失，未执行"],
    },
    "18": {
        "title": "CI、发布与治理",
        "task": "真实构建产物 → sha256 记录 → 安装 → 验证 → 失败回退",
        "blockers": [
            "需要实际发布流水线与可安装产物（安装包/签名/回退脚本执行）；"
            "本轮仅在源码层核对脚本存在，未运行构建与回退",
        ],
        "probes": {"scripts_files": count("FHD/scripts"),
                   "arch_fitness": (ROOT / "FHD/scripts/arch_fitness.py").is_file()},
        "additional_unknowns": ["未产生构建产物与发布回退证据"],
    },
}


def main() -> int:
    out = []
    for domain, rec in RECORDS.items():
        doc = h.evidence(
            domain,
            rec["title"],
            [],
            [],
            task_protocol={
                "task": rec["task"],
                "executed": False,
                "reason": "环境/凭证缺失，未执行真实任务；按协议保持 UNRATED、score=null",
            },
            faults=[],
            unknowns=[*rec["blockers"], *rec["additional_unknowns"]],
            level="UNRATED",
            extra={"probe_facts": rec["probes"], "blocked_reasons": rec["blockers"]},
        )
        p = h.write_doc(doc)
        out.append({"domain": domain, "level": doc["level"], "file": str(p), "blocked": len(rec["blockers"])})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
