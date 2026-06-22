"""Mod 制作端行业预设：写入 manifest.industry 与 config/industry_card.json。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

PRESET_IDS = ("通用", "涂料", "考勤", "批发", "电商", "餐饮", "物流")

_PRESETS: Dict[str, Dict[str, Any]] = {
    "通用": {
        "id": "通用",
        "name": "通用",
        "scenario": "适用于多行业本地 AI 工作台，通过 Mod 扩展具体业务。",
    },
    "涂料": {
        "id": "涂料",
        "name": "涂料/油漆",
        "scenario": "涂料、油漆、固化剂等化工批发与出货。",
    },
    "考勤": {
        "id": "考勤",
        "name": "考勤/排班",
        "scenario": "员工考勤、排班、请假加班与考勤表打印。",
    },
    "批发": {
        "id": "批发",
        "name": "批发/分销",
        "scenario": "多 SKU 批发、客户分级报价与批量开单。",
    },
    "电商": {
        "id": "电商",
        "name": "电商/零售",
        "scenario": "商品、订单与面单发货。",
    },
    "餐饮": {
        "id": "餐饮",
        "name": "餐饮",
        "scenario": "食材、门店订货与厨房领用。",
    },
    "物流": {
        "id": "物流",
        "name": "物流",
        "scenario": "运单、收发方与在途跟踪。",
    },
}


def get_preset(industry_id: str) -> Dict[str, Any]:
    key = (industry_id or "").strip() or "通用"
    base = _PRESETS.get(key) or _PRESETS["通用"]
    return dict(base)


def industry_card_payload(industry_id: str) -> Dict[str, Any]:
    p = get_preset(industry_id)
    return {
        "id": p["id"],
        "name": p["name"],
        "scenario": p["scenario"],
        "description": p["scenario"],
    }


def apply_industry_to_mod_dir(mod_dir: Path, industry_id: str) -> None:
    """创建或更新 Mod 目录内的行业声明（manifest + industry_card）。"""
    p = get_preset(industry_id)
    manifest_path = mod_dir / "manifest.json"
    if not manifest_path.is_file():
        return
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return
    data["industry"] = {
        "id": p["id"],
        "name": p["name"],
        "scenario": p["scenario"],
        "description": p["scenario"],
    }
    fe = data.get("frontend")
    if isinstance(fe, dict):
        shell = fe.get("shell")
        if isinstance(shell, dict):
            settings = shell.get("settings")
            if not isinstance(settings, dict):
                settings = {}
                shell["settings"] = settings
            settings["default_industry"] = p["id"]
            opts = settings.get("industry_options")
            if not isinstance(opts, list):
                settings["industry_options"] = list(PRESET_IDS)
    manifest_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    cfg_dir = mod_dir / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "industry_card.json").write_text(
        json.dumps(industry_card_payload(industry_id), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
