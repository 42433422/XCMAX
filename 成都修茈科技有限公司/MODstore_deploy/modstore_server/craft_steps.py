# ruff: noqa: E402, F401
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from modstore_server.craft_executor import register_craft_step

logger = logging.getLogger(__name__)


_SPEC_DOMAIN_KEYWORDS = {
    "合同": "合同/法务",
    "法律": "合同/法务",
    "合规": "合同/法务",
    "财务": "财务/会计",
    "发票": "财务/会计",
    "报销": "财务/会计",
    "客服": "客服/售后",
    "售后": "客服/售后",
    "退款": "客服/售后",
    "文档": "文档/知识",
    "知识库": "文档/知识",
    "RAG": "文档/知识",
    "电话": "电话/语音",
    "语音": "电话/语音",
    "TTS": "电话/语音",
    "数据分析": "数据/报表",
    "报表": "数据/报表",
    "统计": "数据/报表",
    "SEO": "SEO/站点",
    "站点": "SEO/站点",
    "sitemap": "SEO/站点",
}


from modstore_server.craft_steps_part01 import (
    _craft_spec as _craft_spec,
    _craft_employee_plan as _craft_employee_plan,
    _craft_generate as _craft_generate,
    _craft_validate as _craft_validate,
    _craft_script_workflow as _craft_script_workflow,
    _craft_embed_script as _craft_embed_script,
    _craft_workflow as _craft_workflow,
    _craft_register_pack as _craft_register_pack,
    _craft_workflow_sandbox as _craft_workflow_sandbox,
    _craft_mod_sandbox as _craft_mod_sandbox,
)


from modstore_server.craft_steps_part02 import (
    _craft_standalone_smoke as _craft_standalone_smoke,
    _standalone_smoke_auto_repair as _standalone_smoke_auto_repair,
    _craft_host_check as _craft_host_check,
    _craft_six_dim_gate as _craft_six_dim_gate,
    register_all_craft_steps as register_all_craft_steps,
)
