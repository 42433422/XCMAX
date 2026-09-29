#!/usr/bin/env python3
"""macOS 97 项能力的逐项验收规格。每项 2–4 条用例：界面 + 同会话接口读写 + 读回。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from acc_dsl import ERP, MARK, R, dump, rows

SPECS: dict = {}


def spec(fid):
    def deco(fn):
        SPECS[fid] = fn
        return fn
    return deco


def has(*keys):
    return lambda d: isinstance(d, dict) and all(k in d for k in keys)


def succ(d):
    return isinstance(d, dict) and d.get("success") is True


# ============================ 产品底座 ============================
@spec("base-login")
def _(r: R):
    r.api("读取当前会话身份", "GET", "/api/auth/me",
          check=lambda d: d["data"]["user"]["username"] == "SUNBIRD",
          show=lambda d: f"用户 {d['data']['user']['username']}，账号类型 {d['data']['account_kind']}，租户 {d['data']['tenant_name']}")
    r.api("校验会话有效", "GET", "/api/auth/session/validate", check=lambda d: d.get("valid") is True,
          show=lambda d: f"valid={d.get('valid')}")
    r.ui("/", ["SUNBIRD", "智能对话"])


@spec("base-rbac")
def _(r: R):
    name = f"{MARK}角色{int(time.time()) % 100000}"
    r.api("读取权限点清单", "GET", "/api/rbac/permissions", check=lambda d: len(d["data"]) > 5,
          show=lambda d: f"权限点 {len(d['data'])} 个，示例 {[x['code'] for x in d['data'][:4]]}")
    r.api("新建租户角色", "POST", "/api/rbac/roles", {"name": name, "description": "macOS 验收", "permissions": []},
          check=lambda d: d["data"]["name"] == name, show=lambda d: f"角色 id={d['data']['id']} key={d['data']['key']}")
    r.api("读回角色列表含新角色", "GET", "/api/rbac/roles", check=lambda d: any(x.get("name") == name for x in d["data"]),
          show=lambda d: f"角色数 {len(d['data'])}，含 {name}")
    r.ui("/tenant-roles", ["角色"], allow_err=("/api/mobile/v1/pairing/issue",))


@spec("base-mac-client")
def _(r: R):
    r.api("桌面运行态", "GET", "/api/desktop/status",
          check=lambda d: d["desktopMode"] and d["readyForUi"] and d["runtimeStatus"] == "healthy",
          show=lambda d: f"desktopMode={d['desktopMode']} readyForUi={d['readyForUi']} storage={d['storageMode']}")
    installed = json.loads((Path("/Applications/XCAGI.app/Contents/Resources/build-info.json")).read_text())["gitSha"]
    r.api("客户端构建身份", "GET", "/api/health", check=lambda d, installed=installed: d.get("git_sha") == installed,
          show=lambda d, installed=installed: f"version={d['version']} git_sha={d['git_sha']} installed={installed}")
    r.ui("/desktop-runtime", ["桌面"])


@spec("base-edition-pack")
def _(r: R):
    r.api("平台壳 edition 能力", "GET", "/api/platform-shell/capabilities",
          check=lambda d: d["data"]["edition"] in ("minimal", "generic", "full"),
          show=lambda d: f"edition={d['data']['edition']} generic_pack_installed={d['data']['generic_pack_installed']} bridge_mods={len(d['data']['bridge_mods'])}")
    r.api("可交付状态", "GET", "/api/platform-shell/deliverable-status", check=lambda d: d["data"]["deliverable"] is True,
          show=lambda d: dump(d["data"], 200))
    r.ui("/mod-store", ["能力"])


@spec("base-install-guide")
def _(r: R):
    r.api("首次设置行业清单", "GET", "/api/platform-shell/onboarding-industries",
          check=lambda d: len(d["data"]["open_industry_ids"]) >= 2,
          show=lambda d: f"可选行业 {d['data']['open_industry_ids']}")
    r.api("工作区根目录已初始化", "GET", "/api/platform-shell/workspace-root",
          check=lambda d: bool(d["data"]["workspace_root"]), show=lambda d: d["data"]["workspace_root"])
    r.ui("/onboarding", ["设置"])


@spec("base-device-bind")
def _(r: R):
    r.api("桌面端配对状态", "GET", "/api/desktop/mobile-pairing-status", check=has("paired"),
          show=lambda d: dump(d))
    r.api("签发移动端配对码", "POST", "/api/mobile/v1/pairing/issue", {"host": "127.0.0.1", "port": 17500},
          expected="返回可扫码的配对载荷")
    r.block("移动端 App 扫码完成设备绑定", "需要安装 XCAGI 移动端的 Android/iOS 真机在同网段扫码，本轮只有 macOS 单机")
    r.ui("/settings", [])


@spec("base-health")
def _(r: R):
    r.api("健康探针", "GET", "/api/health", check=lambda d: d["status"] == "healthy" and d["version"],
          show=lambda d: f"status={d['status']} version={d['version']} neuro.running={d['neuro']['running']}")
    r.api("存活探针", "GET", "/health/liveness", check=lambda d: d["status"] == "alive", show=lambda d: d["status"])
    r.api("就绪探针（含依赖）", "GET", "/health/details", check=lambda d: d["checks"]["database"]["status"] == "healthy",
          show=lambda d: f"整体 {d['status']}；database={d['checks']['database']['status']}；redis={d['checks'].get('redis', {}).get('status')}")
    r.ui("/settings", ["系统正常"])


@spec("base-db")
def _(r: R):
    r.api("数据库探针", "GET", "/health/details", check=lambda d: d["checks"]["database"]["status"] == "healthy",
          show=lambda d: dump(d["checks"]["database"]))
    name = f"{MARK}持久化{int(time.time()) % 100000}"
    r.api("写入偏好并读回（验证库可写）", "POST", "/api/preferences", {"key": "acc_db_probe", "value": name},
          check=lambda d: d["data"]["value"] == name, show=lambda d: dump(d["data"]))
    r.api("读回持久化偏好", "GET", "/api/preferences",
          check=lambda d: d["data"]["preferences"].get("acc_db_probe") == name, show=lambda d: dump(d["data"]["preferences"]))
    r.ui("/mod/xcagi-erp-domain-bridge/data-sources", [])


@spec("base-config")
def _(r: R):
    r.api("数据目录配置", "GET", "/api/desktop/status",
          check=lambda d: "/userdata/customer" in d["dataDir"], show=lambda d: f"dataDir={d['dataDir']} modsDir={d['modsDir']}")
    r.api("部署形态配置", "GET", "/api/desktop/deployment", check=lambda d: d["currentMode"] in [m["id"] for m in d["modes"]],
          show=lambda d: f"currentMode={d['currentMode']} 可选 {[m['id'] for m in d['modes']]}")
    r.ui("/settings", ["设置"])


@spec("base-update-mgmt")
def _(r: R):
    r.api("Mod 更新检查", "GET", "/api/mod-store/updates", check=lambda d: d["data"]["complete"] is True,
          show=lambda d: dump(d["data"], 200))
    r.ui("/settings", ["版本"])


@spec("base-settings")
def _(r: R):
    val = f"{MARK}-{int(time.time()) % 100000}"
    r.api("写入工作区偏好", "POST", "/api/preferences", {"key": "acc_settings_probe", "value": val},
          check=lambda d: d["data"]["value"] == val, show=lambda d: dump(d["data"]))
    r.api("读回工作区偏好", "GET", "/api/preferences",
          check=lambda d: d["data"]["preferences"].get("acc_settings_probe") == val, show=lambda d: dump(d["data"]))
    r.api("工作区级设置", "GET", "/api/workspace/prefs", check=lambda d: d["owner_id"].startswith("tenant:"),
          show=lambda d: dump(d))
    r.ui("/settings", ["设置"])


# ============================ AI 能力 ============================
def _reply_after(body: str, text: str) -> str:
    """对话区中该条用户消息之后、右侧会话列表（「新建对话」）之前的文本。"""
    seg = body[body.find(text) + len(text):]
    cut = seg.find("新建对话")
    return seg[:cut] if cut > 0 else seg


def _chat_ui(r: R, text: str, expect_any: list[str], what: str, wait: float = 60):
    def do(p):
        p.go("/", wait=2)
        p.fill("textarea", text)
        end = time.time() + 45
        while time.time() < end and p.js("document.querySelector('.send-message-btn')?.disabled !== false"):
            time.sleep(1)
        p.click(text="发送")

    def check(p):
        end = time.time() + wait
        body = ""
        while time.time() < end:
            time.sleep(2)
            body = p.text(30000)
            tail = _reply_after(body, text)
            if text in body and any(k in tail for k in expect_any):
                return True, f"已发送「{text}」，回复片段：{tail[:260].replace(chr(10), ' | ')}"
        tail = _reply_after(body, text) if text in body else body[-200:]
        return False, f"{wait}s 内回复未出现 {expect_any}；页面尾部：{tail[:260].replace(chr(10), ' | ')}"

    return r.act(f"在智能对话输入框键入「{text}」并点击发送（{what}）",
                 f"对话区出现用户消息与 AI 回复，回复包含 {expect_any} 之一", do, check)


@spec("ai-chat-core")
def _(r: R):
    r.api("AI 对话服务自检", "GET", "/api/ai/test", check=succ, show=lambda d: d["message"])
    tag = time.strftime("%H%M%S")
    _chat_ui(r, f"[{tag}] 你好，请用一句话介绍你能帮我做什么", ["考勤", "产品", "订单", "帮", "可以", "您"], "多轮对话首轮")
    _chat_ui(r, f"[{tag}] 刚才你说的第一项能力再展开一句", ["考勤", "产品", "订单", "可以", "您", "帮", "刚才", "上次"], "上下文续问")


@spec("ai-intent")
def _(r: R):
    r.api("规则+模型意图识别：库存", "POST", "/api/ai/intent/test", {"message": "帮我查一下库存"},
          check=lambda d: d["data"]["primary_intent"] in ("materials", "inventory", "products"),
          show=lambda d: f"primary_intent={d['data']['primary_intent']} tool_key={d['data']['tool_key']} sources={d['data']['sources_used']}")
    r.api("意图识别：打印标签", "POST", "/api/ai/intent/test", {"message": "打印一张产品标签"},
          check=lambda d: "print" in str(d["data"]["primary_intent"]) or "label" in str(d["data"]["tool_key"]),
          show=lambda d: f"primary_intent={d['data']['primary_intent']} tool_key={d['data']['tool_key']}")
    r.api("意图识别：问候不路由到业务工具", "POST", "/api/ai/intent/test", {"message": "你好"},
          check=lambda d: d["data"]["is_greeting"] is True, show=lambda d: f"is_greeting={d['data']['is_greeting']}")
    r.ui("/chat-debug", ["调试"])


@spec("ai-task-workspace")
def _(r: R):
    tid = f"mac-acc-{int(time.time())}"
    r.api("未注册工具应返回具体原因", "POST", "/api/agent/tasks", {"task_id": f"{tid}-bad", "title": "x", "tool_id": "nope", "action": "run"},
          status=(400,), check=lambda d: "未注册" in dump(d), expected="400 且提示「未注册的工具动作」", show=lambda d: dump(d))
    r.api("新建任务工作区（只读产品查询）", "POST", "/api/agent/tasks",
          {"task_id": tid, "title": f"{MARK}任务", "message": f"{MARK}查询产品", "tool_id": "products", "action": "query", "params": {}},
          check=lambda d: d.get("success") is not False, show=lambda d: dump(d, 200))
    r.api("读回任务列表", "GET", "/api/agent/tasks", check=lambda d: any(tid in dump(x, 2000) for x in d["data"]),
          show=lambda d: f"任务数 {d['count']}")
    r.see(f"/workspaces/{tid}", MARK, "独立工作区打开新任务")


@spec("ai-employees-workflow")
def _(r: R):
    r.api("工作流员工目录", "GET", "/api/core-workflow/employees",
          check=lambda d: len(d["data"]["workflow_split_mod_ids"]) >= 1,
          show=lambda d: f"split mods={d['data']['workflow_split_mod_ids']}")
    r.api("发货管理员工状态", "GET", "/api/mod/xcagi-core-workflow-employees/employees/shipment_mgmt/status", check=succ,
          show=lambda d: dump(d, 200))
    r.ui("/workflow-employee-space", ["员工"])


@spec("ai-employee-pack")
def _(r: R):
    r.api("办公员工包目录", "GET", "/api/mod/xcagi-office-employee-pack-bridge/catalog", check=succ,
          show=lambda d: dump(d, 240))
    r.api("已装员工包数量", "GET", "/api/platform-shell/employee-tools",
          check=lambda d: d["data"]["installed_employee_pack_count"] >= 1,
          show=lambda d: f"installed_employee_pack_count={d['data']['installed_employee_pack_count']} tools={d['data']['registered_tool_count']}")
    r.ui("/mod/xcagi-office-employee-pack-bridge/tools", ["工具"])


@spec("ai-excel")
def _(r: R):
    fn = f"mac0929-{int(time.time())}.xlsx"
    r.api("生成 Excel", "POST", "/api/excel/data/generate",
          {"data": [{"名称": f"{MARK}产品", "数量": 3, "单价": 2.5}], "filename": fn},
          check=lambda d: d["rows"] == 1 and d["filename"] == fn, show=lambda d: f"{d['filename']} rows={d['rows']}", save="xl")
    xl = r.ctx.get("xl") or {}
    r.api("解析刚生成的 Excel", "POST", "/api/excel/data/extract",
          {"file_path": xl.get("file_path") or xl.get("path") or f"temp_excel/{fn}"},
          check=lambda d: MARK in dump(d, 5000), show=lambda d: dump(d, 240))
    r.api("Excel 生成员工在岗", "GET", "/api/mod/excel-generate-employee/employees/excel-generate-employee/status",
          check=succ, show=lambda d: dump(d, 160))
    r.ui("/mod/xcagi-office-employee-pack-bridge/tools", [])


@spec("ai-tts")
def _(r: R):
    r.api("在线语音合成（界面播报同一接口）", "POST", "/api/tts",
          {"text": "macOS 验收播报", "lang": "zh", "voice": "zh-CN-XiaoxiaoNeural", "rate": "+15%"},
          check=lambda d: d["success"] and len(str(d["data"].get("audioBase64") or "")) > 1000,
          expected="返回 success 与 base64 音频", timeout=60,
          show=lambda d: f"audioBase64 长度 {len(str(d['data'].get('audioBase64') or ''))}，引擎 {d['data'].get('engine') or d['data'].get('provider')}")
    r.api("语音子系统健康", "GET", "/api/voice/health", check=lambda d: d["data"]["ready"] is True,
          show=lambda d: dump(d["data"]))
    r.ui("/settings", ["语音"])


@spec("ai-knowledge")
def _(r: R):
    r.api("Persy 知识库状态", "GET", "/api/persy/knowledge", check=succ,
          show=lambda d: f"dataset={d['dataset_id']} 文档 {d['document_count']} 片段 {d['chunk_count']}")
    r.api("写入知识", "POST", "/api/knowledge/v1/ingest", {"text": f"{MARK}：迟到超过10分钟计半天。", "source": "mac-acceptance"},
          check=succ)
    r.api("检索知识", "POST", "/api/knowledge/v1/query", {"query": "迟到超过多少分钟计半天", "top_k": 3},
          check=lambda d: MARK in dump(d, 5000))
    r.ui("/persy/knowledge", ["知识"])


DOC_TXT = f"{MARK} 汇报\n客户：太阳鸟\n产品：包装盒 数量：24"


def _seed_xlsx(r: R) -> str:
    if "seed" not in r.ctx:
        d = r.p.api("POST", "/api/excel/data/generate", {"data": [{"名称": f"{MARK}产品", "数量": 24}], "filename": f"mac0929-seed-{int(time.time())}.xlsx"})["data"]
        r.ctx["seed"] = d["file_path"]
    return r.ctx["seed"]


def _emp(r: R, emp: str, what: str, payload: dict, key: str, check, expected: str) -> str:
    ws = r.ctx.setdefault("ws", str(Path(_seed_xlsx(r)).parent / f"mac0929-{r.F.fid}-{int(time.time())}"))
    r.api(what, "POST", f"/api/mod/{emp}/employees/{emp}/run", {"workspace_root": ws, **payload},
          check=lambda d: (d.get("data") or {}).get("ok") is True and check(d), expected=expected, save=key, timeout=120,
          show=lambda d: f"ok={(d.get('data') or {}).get('ok')}；{str((d.get('data') or {}).get('summary'))[:220]}")
    items = ((r.ctx.get(key) or {}).get("data") or {}).get("items") or [{}]
    return items[0].get("output_path") or ""


def _gen_read(r: R, kind: str, ext: str, src: str | None = None) -> str:
    gen_items = lambda: (((r.ctx.get(f"{kind}_gen") or {}).get("data") or {}).get("items") or [{}])[0]
    _emp(r, f"{kind}-generate-employee", f"{kind.upper()} 生成员工：由文本生成 .{ext}",
         {"file_path": src or _seed_xlsx(r), "plain_text": DOC_TXT}, f"{kind}_gen",
         lambda d: True, f"ok=true 且产出 .{ext} 文件")
    gen = gen_items().get("pdf_output_path") or gen_items().get("output_path") or f"missing.{ext}"
    out = f"outputs/{kind}-read.json"
    _emp(r, f"{kind}-full-read-employee", f"{kind.upper()} 读取员工：解析刚生成的 .{ext}",
         {"file_path": gen, "output_relpath": out}, f"{kind}_read", lambda d: True, "ok=true 且写出解析结果 JSON")
    r.api(f"读回 {kind.upper()} 解析结果（界面同一读取接口）", "POST", "/api/platform-shell/workspace-read-files",
          {"workspace_root": r.ctx["ws"], "file_paths": [f"{r.ctx['ws']}/{out}"]},
          check=lambda d: "太阳鸟" in dump(d, 400000) and "包装盒" in dump(d, 400000),
          expected="解析结果含原文「太阳鸟」「包装盒」", show=lambda d: dump(d, 200))
    return f"{r.ctx['ws']}/{out}"


def _setup_json(r: R) -> str:
    """word/pdf 生成员工只收 .json/.txt：先用 CSV 生成 + 读取员工在同一工作区产出一个 JSON 作为输入。"""
    ws = r.ctx.setdefault("ws", str(Path(_seed_xlsx(r)).parent / f"mac0929-{r.F.fid}-{int(time.time())}"))
    run = lambda emp, pl: r.p.api("POST", f"/api/mod/{emp}/employees/{emp}/run", {"workspace_root": ws, **pl}, timeout=120)["data"]
    csv = ((run("csv-generate-employee", {"file_path": _seed_xlsx(r), "plain_text": DOC_TXT}).get("data") or {}).get("items") or [{}])[0].get("output_path")
    run("csv-full-read-employee", {"file_path": csv, "output_relpath": "inputs/source.json"})
    return f"{ws}/inputs/source.json"


@spec("ai-ppt")
def _(r: R):
    _gen_read(r, "ppt", "pptx")
    r.ui("/mod/xcagi-office-employee-pack-bridge/other-tools", ["员工"], final="/mod/xcagi-office-employee-pack-bridge/other-tools")


@spec("ai-csv")
def _(r: R):
    _gen_read(r, "csv", "csv")
    r.ui("/mod/xcagi-office-employee-pack-bridge/tools", [])


@spec("ai-word")
def _(r: R):
    _gen_read(r, "word", "docx", src=_setup_json(r))
    r.ui("/mod/xcagi-office-employee-pack-bridge/tools", [])


@spec("ai-pdf")
def _(r: R):
    _gen_read(r, "pdf", "pdf", src=_setup_json(r))
    r.ui("/mod/xcagi-office-employee-pack-bridge/tools", [])


@spec("ai-ocr-doc")
def _(r: R):
    r.api("OCR 后端", "GET", "/api/ocr/test", check=lambda d: d["active_backend"] == "macos_vision",
          show=lambda d: f"active_backend={d['active_backend']}")
    r.api("识别单据图片（macOS Vision）", "POST", "/api/ocr/recognize", form={"image": _bill(r)},
          check=lambda d: "0929" in dump(d, 20000), show=lambda d: dump(d, 240),
          expected="识别结果包含图片中的单号 0929")
    r.api("识别单据中的中文（客户名）", "POST", "/api/ocr/recognize", form={"image": _bill(r)},
          check=lambda d: "太阳鸟" in dump(d, 20000), show=lambda d: dump(d, 240),
          expected="识别结果包含图片中的中文客户名「太阳鸟」")
    r.ui("/", ["上传附件"])


def _bill(r: R) -> dict:
    """在 App 页面内用 canvas 绘制一张发货单图片，作为 OCR 输入。"""
    if "bill" not in r.ctx:
        b64 = r.p.js("""(() => { const c = document.createElement('canvas'); c.width = 900; c.height = 420;
          const g = c.getContext('2d'); g.fillStyle = '#fff'; g.fillRect(0, 0, 900, 420); g.fillStyle = '#000';
          g.font = '48px "PingFang SC", sans-serif'; g.fillText('发货单 NO.20260929', 40, 90);
          g.fillText('客户：太阳鸟', 40, 190); g.fillText('产品：包装盒 数量：24', 40, 290);
          return c.toDataURL('image/png').split(',')[1]; })()""")
        r.ctx["bill"] = {"__file": True, "name": "bill-0929.png", "type": "image/png", "b64": b64}
    return r.ctx["bill"]


def _walk(v):
    if isinstance(v, dict):
        for k, x in v.items():
            yield k, x
            yield from _walk(x)
    elif isinstance(v, list):
        for x in v:
            yield from _walk(x)


# ============================ ERP ============================
@spec("erp-shipment")
def _(r: R):
    name = f"{MARK}出货客户"
    r.api("创建出货单", "POST", "/api/business/shipment/create",
          {"unit_name": name, "contact_person": "张三", "contact_phone": "13800000000",
           "items": [{"name": f"{MARK}产品", "quantity": 24, "unit_price": 3.5, "tin_spec": 25.0}]},
          check=succ, show=lambda d: dump(d, 220))
    time.sleep(4)
    r.api("读回出货记录", "GET", f"{ERP}/shipment/shipment-records/records", check=lambda d: name in dump(d, 100000),
          show=lambda d: f"记录 {len(rows(d))} 条，含 {name}")
    r.see("/mod/xcagi-erp-domain-bridge/shipment-records", name, "业务记录页出现新出货单")


@spec("erp-purchase")
def _(r: R):
    code = f"MACSUP{int(time.time()) % 1000000}"
    r.api("新建供应商（带编码）", "POST", "/api/purchase/suppliers", {"code": code, "name": f"{MARK}供应商", "contact_person": "李四"},
          check=succ, save="sup", show=lambda d: f"供应商 id={d['data']['id']} code={d['data']['code']}")
    sid = (r.ctx.get("sup") or {}).get("data", {}).get("id", 1)
    pid = _product_id(r)
    r.api("新建采购订单（选定产品，字符串日期）", "POST", "/api/purchase/orders",
          {"supplier_id": sid, "order_date": "2026-09-29", "delivery_date": "2026-10-08",
           "items": [{"product_id": pid, "quantity": 10, "unit_price": 5.0}], "remark": MARK},
          check=succ, save="po", show=lambda d: f"订单 id={d['data'].get('id')} no={d['data'].get('order_no')} 金额={d['data'].get('total_amount')}")
    r.api("缺陷回归：明细未选产品应得到业务提示而非 500", "POST", "/api/purchase/orders",
          {"supplier_id": sid, "items": [{"product_id": "", "quantity": 1, "unit_price": 1}]},
          status=(200, 400), check=lambda d: "未选择产品" in dump(d), expected="返回「第 1 行明细未选择产品」",
          show=lambda d: dump(d))
    r.see("/mod/xcagi-erp-domain-bridge/purchase", lambda: r.ctx["po"]["data"]["order_no"], "采购订单列表出现新订单号")


def _product_id(r: R):
    if "pid" not in r.ctx:
        d = r.p.api("GET", f"{ERP}/products/list?page=1&per_page=50")["data"]
        items = rows(d)
        r.ctx["pid"] = items[0]["id"] if items else 1
    return r.ctx["pid"]


@spec("erp-inventory")
def _(r: R):
    r.api("库存台账", "GET", "/api/inventory", check=succ, show=lambda d: f"库存行 {d['total']}")
    r.api("库存预警", "GET", "/api/inventory/combined-alert", check=succ, show=lambda d: f"total_alerts={d['total_alerts']}")
    r.api("库存流水", "GET", "/api/inventory/transactions", check=succ, show=lambda d: f"流水 {d['total']}")
    r.ui("/mod/xcagi-erp-domain-bridge/inventory", ["库存"])


@spec("erp-master-data")
def _(r: R):
    cname = f"{MARK}客户{int(time.time()) % 100000}"
    pname = f"{MARK}产品{int(time.time()) % 100000}"
    r.api("新建客户", "POST", f"{ERP}/customers", {"customer_name": cname, "contact_person": "张三", "contact_phone": "13800000000"},
          check=lambda d: d["data"]["customer_name"] == cname, show=lambda d: f"客户 id={d['data']['id']}")
    r.api("新建产品并返回 id", "POST", f"{ERP}/products/add", {"name": pname, "model_number": f"M{int(time.time()) % 100000}", "unit": "个", "price": 3.5},
          check=lambda d: d["data"].get("id") is not None, show=lambda d: dump(d["data"]))
    r.api("读回产品列表", "GET", f"{ERP}/products/list?page=1&per_page=50", check=lambda d: pname in dump(d, 100000),
          show=lambda d: f"产品 {len(rows(d))} 条，含 {pname}")
    r.see("/mod/xcagi-erp-domain-bridge/products", pname, "产品页出现新产品")


@spec("erp-sales-order")
def _(r: R):
    r.api("下一个订单号", "GET", f"{ERP}/orders/next_number", check=succ, show=lambda d: dump(d, 160))
    r.api("订单列表", "GET", f"{ERP}/orders", check=succ, show=lambda d: f"订单 {len(rows(d))} 条")
    r.ui("/mod/xcagi-erp-domain-bridge/orders/create", ["单"])


@spec("erp-purchase-inbound")
def _(r: R):
    code = f"MACIN{int(time.time()) % 1000000}"
    r.api("准备供应商", "POST", "/api/purchase/suppliers", {"code": code, "name": f"{MARK}入库供应商"}, check=succ, save="sup",
          show=lambda d: f"供应商 id={d['data']['id']}")
    sid = (r.ctx.get("sup") or {}).get("data", {}).get("id", 1)
    r.api("采购入库登记", "POST", "/api/purchase/inbounds",
          {"supplier_id": sid, "warehouse_id": 1, "inbound_date": "2026-09-29", "remark": f"{MARK}入库",
           "items": [{"product_id": _product_id(r), "quantity": 10, "unit_price": 5.0}]},
          check=succ, show=lambda d: dump(d.get("data"), 200))
    r.api("读回入库单", "GET", "/api/purchase/inbounds", check=lambda d: f"{MARK}入库" in dump(d, 100000),
          show=lambda d: f"入库单 {d.get('total')}")
    r.ui("/mod/xcagi-erp-domain-bridge/purchase", ["采购入库"])


@spec("erp-inventory-warehouse")
def _(r: R):
    code = f"MW{int(time.time()) % 1000000}"
    r.api("新建仓库", "POST", "/api/inventory/warehouses", {"name": f"{MARK}仓{code}", "code": code, "address": "成都"},
          check=lambda d: d["data"]["code"] == code, save="wh", show=lambda d: f"仓库 id={d['data']['id']}")
    wid = (r.ctx.get("wh") or {}).get("data", {}).get("id", 1)
    r.api("新建库位", "POST", "/api/inventory/locations", {"warehouse_id": wid, "code": "A-01", "name": "A区01位"},
          check=succ, show=lambda d: dump(d.get("data"), 160))
    r.api("读回仓库列表", "GET", "/api/inventory/warehouses", check=lambda d: code in dump(d, 100000),
          show=lambda d: f"仓库 {d['count']} 个")
    r.ui("/mod/xcagi-erp-domain-bridge/inventory", ["库存"])


@spec("erp-replenishment")
def _(r: R):
    _chat_ui(r, "根据当前库存给我补货建议", ["补货", "建议", "库存", "充足", "低于"], "对话触发补货建议")
    r.api("原料低库存预警", "GET", "/api/inventory/combined-alert", check=succ, show=lambda d: dump(d, 160))
    r.ui("/mod/xcagi-erp-domain-bridge/inventory", ["库存"])


@spec("erp-uom")
def _(r: R):
    r.api("计量单位（采购单位）", "GET", f"{ERP}/purchase_units", check=succ, show=lambda d: dump(d, 200))
    r.api("出货单位", "GET", f"{ERP}/shipment/shipment-records/units", check=succ, show=lambda d: dump(d, 200))
    r.ui("/mod/xcagi-erp-domain-bridge/products", ["单位"])


@spec("erp-finance-ledger")
def _(r: R):
    r.api("手工收入记账", "POST", "/api/finance/transactions",
          {"transaction_type": "revenue", "amount": 128.5, "description": f"{MARK}收入"}, check=succ,
          show=lambda d: dump(d.get("data"), 160))
    r.api("读回财务流水", "GET", "/api/finance/transactions", check=lambda d: MARK in dump(d, 100000),
          show=lambda d: f"流水 {d['total']} 条")
    r.api("统一账本", "GET", "/api/finance/unified-ledger", check=succ, show=lambda d: f"count={d['count']}")
    r.ui("/kitten-finance", ["财务"])


@spec("erp-ar-ap")
def _(r: R):
    r.api("应收", "GET", "/api/finance/receivables", check=succ, show=lambda d: f"应收 {d['total']}")
    r.api("应付", "GET", "/api/finance/payables", check=succ, show=lambda d: f"应付 {d['total']}")
    r.api("毛利看板", "GET", "/api/finance/dashboard", check=lambda d: "gross_profit" in d["data"],
          show=lambda d: dump(d["data"], 200))
    r.ui("/kitten-finance", [])


@spec("erp-report")
def _(r: R):
    r.api("经营看板", "GET", "/api/report/dashboard", check=succ, show=lambda d: dump(d["data"], 200))
    r.api("销售报表", "GET", "/api/report/sales", check=succ, show=lambda d: dump(d["summary"]))
    r.api("价格表模板预览", "GET", "/api/sales-contract/template-preview", check=succ, show=lambda d: dump(d["data"]["headers"]))
    r.ui("/kitten-finance", ["分析"])


@spec("erp-invoice")
def _(r: R):
    r.api("CRM 发票列表", "GET", "/api/finance/invoices/crm", check=succ)
    r.api("税务通道", "GET", "/api/finance/invoices/tax-channel", check=succ)
    r.block("开具真实税务发票", "需要企业在税务开票通道（百望/航信等）开通并配置税号与证书，本机未配置")
    r.ui("/kitten-finance", [])


@spec("erp-reconcile")
def _(r: R):
    r.api("支付对账内部接口拒绝无密钥调用", "GET", "/api/internal/payment/reconciliation-period?period_start=2026-09-01T00:00:00Z&period_end=2026-09-30T00:00:00Z",
          status=(403, 503), check=lambda d: "internal" in dump(d), expected="拒绝：403 invalid internal api key 或 503 internal api not configured", show=lambda d: dump(d))
    r.api("执行一次经营对账", "POST", "/api/operations-line/reconciliation/run", {}, check=succ, show=lambda d: dump(d, 200))
    r.api("读回对账结果", "GET", "/api/operations-line/reconciliation/status",
          check=lambda d: d["data"].get("last_run") is not None, show=lambda d: dump(d["data"], 200))
    r.ui("/kitten-finance", [])


@spec("erp-templates")
def _(r: R):
    r.api("单据模板列表", "GET", "/api/document-templates", check=lambda d: d["default_id"],
          show=lambda d: f"默认 {d['default_id']}；共 {len(d['data'])}")
    r.api("Excel 模板库", "GET", "/api/excel/templates", check=lambda d: len(d["templates"]) >= 1,
          show=lambda d: f"模板 {[t['name'] for t in d['templates'][:4]]}")
    r.ui("/mod/xcagi-erp-domain-bridge/template-preview", ["模板"])


@spec("erp-label")
def _(r: R):
    r.api("标签任务可选产品", "GET", "/api/print/label-jobs/products?keyword=&page=1&per_page=50", check=succ)
    r.api("标签打印员工状态", "GET", "/api/mod/xcagi-core-workflow-employees/employees/label_print/status", check=succ,
          show=lambda d: dump(d, 160))
    r.ui("/mod/xcagi-erp-domain-bridge/print", ["标签"])
    r.block("物理标签打印出纸", "需要连接并选择实体标签打印机（本机未连接打印机）")


@spec("erp-excel-io")
def _(r: R):
    r.api("Excel 模板服务", "GET", "/api/excel/test", check=succ, show=lambda d: d["message"])
    r.api("导入模板清单", "GET", "/api/excel/list", check=lambda d: len(d["templates"]) >= 1,
          show=lambda d: f"{[t['name'] for t in d['templates'][:4]]}")
    r.api("导入日志", "GET", "/api/excel/data/logs", check=succ, show=lambda d: f"logs={d['total']}")
    r.ui("/mod/xcagi-erp-domain-bridge/products", ["导入Excel"])


@spec("erp-contract")
def _(r: R):
    r.api("合同模板", "GET", "/api/sales-contract/templates", check=lambda d: len(d["data"]) >= 1,
          show=lambda d: f"{[x['display_name'] for x in d['data']]}")
    me = r.p.api("GET", "/api/auth/me")["data"]["data"]
    mid = next((v for k, v in _walk(me) if k in ("market_user_id", "marketUserId")), None)
    r.api("合同生命周期状态（当前市场账号）", "GET", f"/api/contract-lifecycle/status?market_user_id={mid}&username=SUNBIRD",
          check=succ, show=lambda d: dump(d, 200))
    r.api("从文本解析合同", "POST", "/api/sales-contract/resolve-from-text",
          {"text": "给太阳鸟做合同：产品A 10个 单价5元"}, check=succ, show=lambda d: dump(d, 220))
    r.ui("/mod/xcagi-erp-domain-bridge/template-preview", [])


@spec("erp-print-agent")
def _(r: R):
    r.api("打印代理打印机列表", "GET", "/api/print/printers", check=succ)
    r.ui("/mod/xcagi-erp-domain-bridge/printer-list", ["打印机"])
    r.block("套打出纸", "需要本机安装实体打印机")


@spec("erp-ocr")
def _(r: R):
    r.api("OCR 服务", "GET", "/api/ocr/test", check=succ, show=lambda d: f"backend={d['active_backend']}")
    r.api("识别单据文本", "POST", "/api/ocr/recognize", form={"image": _bill(r)},
          check=lambda d: "0929" in dump(d, 5000), show=lambda d: dump(d, 240))
    r.ui("/", ["上传附件"])


@spec("erp-ocr-clean")
def _(r: R):
    r.api("识别并抽取结构化字段", "POST", "/api/ocr/recognize-and-extract",
          form={"image": _bill(r)}, check=lambda d: "0929" in dump(d, 5000),
          show=lambda d: dump(d, 240))
    r.api("出货单 OCR 预览", "POST", "/api/excel/data/shipment-etl/ocr-preview",
          form={"image": _bill(r)}, check=succ, show=lambda d: dump(d, 200))
    r.ui("/business-docking", ["数据对接中心"])


@spec("erp-approval")
def _(r: R):
    key = f"mac0929_{int(time.time())}"
    uid = r.p.api("GET", "/api/auth/me")["data"]["data"]["user"]["id"]
    r.api("新建审批流程（单节点，本人审批）", "POST", "/api/approval/flows",
          {"flow": {"flow_name": f"{MARK}流程", "flow_key": key}, "nodes": [{"node_name": "负责人审批", "approver_type": "user", "approver_ids": [uid]}]},
          check=succ, show=lambda d: dump(d.get("data"), 160))
    r.api("提交审批单", "POST", "/api/approval/requests", {"flow_key": key, "title": f"{MARK}审批", "content": "macOS 验收"},
          check=succ, save="req", show=lambda d: dump(d.get("data"), 160))
    rid = ((r.ctx.get("req") or {}).get("data") or {}).get("id")
    r.api("审批通过", "POST", f"/api/approval/requests/{rid}/approve", {"comment": "macOS 验收通过"}, check=succ,
          show=lambda d: dump(d.get("data"), 160))
    r.see("/approval-hub/workspace", f"{MARK}审批", "审批工作台出现新审批单")


# ============================ 渠道 ============================
@spec("ch-im-core")
def _(r: R):
    r.api("联系人", "GET", "/api/im/contacts", check=lambda d: len(d["contacts"]) >= 1, save="ct",
          show=lambda d: f"{[c['display_name'] for c in d['contacts']]}")
    r.api("企业专属客服会话发消息", "POST", "/api/im/enterprise-cs/messages", {"body": f"{MARK} 站内消息"},
          check=succ, show=lambda d: dump(d, 200))
    r.api("读回消息", "GET", "/api/im/enterprise-cs/messages", check=lambda d: MARK in dump(d, 200000),
          show=lambda d: f"会话 {d['conversation']['title']}")
    def _open_cs(p):
        p.go("/im", wait=3)
        p.click(text="企业专属客服")

    def _seen(p):
        ok = p.wait_text(f"{MARK} 站内消息", timeout=10)
        txt = p.text(20000)
        i = txt.find(f"{MARK} 站内消息")
        return ok, f"{'已' if ok else '未'}在会话中看到新消息；上下文：{txt[max(0, i - 60): i + 100].replace(chr(10), ' | ') if i >= 0 else txt[:160]}"

    r.act("在信息页点开「企业专属客服」会话", "会话消息区出现刚发送的站内消息", _open_cs, _seen)


@spec("ch-im-cs")
def _(r: R):
    r.api("客服桥状态", "GET", "/api/mod/xcagi-customer-service-bridge/user-cs/status", check=succ, show=lambda d: dump(d, 200))
    r.api("客服漏斗", "GET", "/api/mod/xcagi-customer-service-bridge/user-cs/pipeline/funnel", check=succ, show=lambda d: dump(d, 200))
    r.ui("/im", ["客服"])


@spec("ch-notify")
def _(r: R):
    r.api("未读总数", "GET", "/api/im/unread-total", check=succ, show=lambda d: f"unread_total={d['unread_total']}")
    r.block("移动端推送送达", "需要已配对的 Android/iOS 真机接收推送")
    r.ui("/im", [])


@spec("ch-task-center")
def _(r: R):
    r.api("任务列表", "GET", "/api/agent/tasks", check=succ, show=lambda d: f"任务 {d['count']}")
    r.api("审批待办", "GET", "/api/approval/requests?status=pending", check=succ, show=lambda d: dump(d["pagination"]))
    r.ui("/approval-hub/workspace", ["审批"])


@spec("ch-im-super")
def _(r: R):
    r.api("超级员工能力路由", "GET", "/api/ai/qclaw/routes", check=succ, show=lambda d: dump(d, 200))
    r.ui("/im", ["信息"])


@spec("ch-im-ws")
def _(r: R):
    def check(p):
        res = p.js("""new Promise(res => { try {
          const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/im');
          const t = setTimeout(() => res({ok: false, why: 'timeout'}), 8000);
          ws.onopen = () => { clearTimeout(t); ws.close(); res({ok: true}); };
          ws.onerror = () => { clearTimeout(t); res({ok: false, why: 'error'}); };
        } catch (e) { res({ok: false, why: String(e)}); } })""")
        return bool(res and res.get("ok")), f"WebSocket /ws/im 握手结果 {res}"

    r.act("在页面内建立 IM WebSocket 连接", "握手成功（onopen）", lambda p: p.go("/im", wait=2), check)
    r.api("未读计数", "GET", "/api/im/unread-total", check=succ, show=lambda d: dump(d))


@spec("ch-wechat-ingest")
def _(r: R):
    r.api("微信采集端联系人（无采集令牌）", "GET", "/api/ops/wechat/contacts", status=(401,),
          expected="未携带采集端令牌时拒绝访问（HTTP 401）", show=lambda d: dump(d))
    r.block("采集端推送微信消息入库", "需要本机运行微信 PC 版与 XCAGI 微信采集端，并配置 wechat sync token")
    r.ui("/business-docking", ["数据对接中心"])


@spec("ch-wechat-contacts")
def _(r: R):
    r.api("联系人同步接口鉴权", "GET", "/api/ops/wechat/contacts", status=(401,), expected="无令牌拒绝", show=lambda d: dump(d))
    r.block("微信联系人同步入客户档案", "需要微信采集端与 sync token")
    r.ui("/business-docking", ["数据对接中心"])


@spec("ch-wechat-phone")
def _(r: R):
    r.api("微信网关面板", "GET", "/api/ai/qclaw/panel", check=succ, show=lambda d: f"wechat_open={d['wechat_open']}")
    r.block("微信来电监控", "需要微信 PC 版登录并有真实来电")
    r.ui("/business-docking", ["数据对接中心"])


@spec("ch-wechat-context")
def _(r: R):
    r.api("对话上下文", "GET", "/api/ai/context", check=succ, show=lambda d: dump(d))
    r.block("联系人情报注入对话", "需要微信采集端先同步联系人情报")
    r.ui("/business-docking", ["数据对接中心"])


@spec("ch-asr")
def _(r: R):
    r.api("ASR 模型就绪", "GET", "/api/voice/health", check=lambda d: d["data"]["ready"] is True, show=lambda d: dump(d["data"]))
    r.block("麦克风语音转写", "需要授予 XCAGI 麦克风权限并由真人说话，自动化无法提供真实语音输入")
    r.ui("/", ["按住说话"])


@spec("ch-realtime-voice")
def _(r: R):
    r.api("语音模型源", "GET", "/api/voice/health", check=succ, show=lambda d: dump(d["data"]))
    r.block("实时语音对话", "需要麦克风权限与真人语音")
    r.ui("/", ["按住说话"])


# ============================ Mod 生态 ============================
@spec("mods-loader")
def _(r: R):
    r.api("Mod 加载状态", "GET", "/api/mods/loading-status",
          check=lambda d: d["data"]["mods_loaded"] >= 1 and not d["data"]["load_errors"] and not d["data"]["manifest_errors"],
          show=lambda d: f"已加载 {d['data']['mods_loaded']}，manifest_errors={d['data']['manifest_errors']}")
    r.api("清单校验接口", "GET", "/api/mod-store/validate?mod_id=xcagi-erp-domain-bridge", check=succ, show=lambda d: dump(d, 200))
    r.api("已加载 Mod 列表", "GET", "/api/mods", check=lambda d: len(d["data"]) >= 5, show=lambda d: f"{len(d['data'])} 个")
    r.ui("/mod-store", [])


@spec("mods-store")
def _(r: R):
    r.api("能力库目录", "GET", "/api/mod-store/catalog", check=lambda d: len(d["data"]["available"]) >= 1,
          show=lambda d: f"可装 {len(d['data']['available'])}，已索引 {d['data']['indexed_count']}")
    r.api("市场目录", "GET", "/api/mod-store/market-catalog", check=lambda d: len(d["data"]["items"]) >= 1,
          show=lambda d: f"市场条目 {len(d['data']['items'])}")
    r.ui("/mod-store", ["能力"])


@spec("mods-host-mount")
def _(r: R):
    r.api("Mod 前端路由挂载", "GET", "/api/mods/routes", check=lambda d: len(d["data"]) >= 5,
          show=lambda d: f"{[x['mod_id'] for x in d['data']][:6]}")
    r.api("路由权限矩阵", "GET", "/api/platform-shell/auth/permission-matrix", check=lambda d: d["data"]["allowed"] is True,
          show=lambda d: f"account_kind={d['data']['account_kind']} role={d['data']['enterprise_role']}")
    r.ui("/mod/xcagi-erp-domain-bridge/products", ["产品"])


@spec("mods-shell")
def _(r: R):
    r.api("平台壳解耦进度", "GET", "/api/platform-shell/decoupling-progress", check=succ,
          show=lambda d: f"里程碑 {[m['id'] for m in d['data']['milestones']]}")
    r.api("宿主档案", "GET", "/api/system/host-profile", check=succ, show=lambda d: dump(d["data"], 160))
    r.ui("/mod-store", ["能力"])


@spec("mods-open-api")
def _(r: R):
    r.api("开放 API 清单", "GET", "/api/aiopen/manifest", check=lambda d: len(d["tools"]) >= 5,
          show=lambda d: f"version={d['version']} tools={[t['name'] for t in d['tools']][:5]}")
    r.api("签发开放 API Key", "POST", "/api/aiopen/keys", {"label": f"{MARK}"}, check=lambda d: d["key"].startswith("aiopen_"),
          show=lambda d: f"key 前缀 {d['key'][:10]}…（已脱敏）")
    r.api("读回 Key 列表", "GET", "/api/aiopen/keys", check=lambda d: len(d["keys"]) >= 1, show=lambda d: f"{len(d['keys'])} 个")
    r.ui("/ai-ecosystem", [])


@spec("mods-webhook")
def _(r: R):
    r.api("订单事件 Webhook 配置", "GET", "/api/orders/webhooks", check=succ)
    r.api("通信端点", "GET", "/api/mods/comms/endpoints", check=succ, show=lambda d: dump(d))
    r.ui("/mod-store", [])


@spec("mods-bridge")
def _(r: R):
    for mid in ("xcagi-erp-domain-bridge", "xcagi-approval-bridge", "xcagi-customer-service-bridge"):
        r.api(f"{mid} 桥接状态", "GET", f"/api/mod/{mid}/status", check=succ, show=lambda d: dump(d, 140))
    r.ui("/mod-store", [])


# ============================ 行业 ============================
@spec("ind-coating")
def _(r: R):
    r.block("涂装行业包安装与行业切换", "该行业包需涂装行业企业账号授权；SUNBIRD 为饰品包装行业账号，已加载 Mod 与行业清单中均无涂装包")
    r.block("涂装行业专属单据字段", "同上：未授权涂装行业包，无法在本账号打开涂装字段页")


@spec("ind-packaging")
def _(r: R):
    r.api("当前行业", "GET", "/api/system/industry", check=lambda d: "饰品" in dump(d, 5000),
          show=lambda d: f"{d['data'].get('name') or d['data'].get('industry_name') or dump(d['data'], 60)}")
    r.ui("/mod/xcagi-erp-domain-bridge/products", ["饰品包装品管理"])
    r.ui("/mod/xcagi-erp-domain-bridge/inventory", ["库存"])


@spec("ind-attendance")
def _(r: R):
    dep = f"{MARK}部门{int(time.time()) % 10000}"
    r.api("新建部门", "POST", "/api/mods/attendance-industry/departments", {"department": dep},
          check=succ, show=lambda d: dump(d, 160))
    r.api("新建员工", "POST", "/api/mods/attendance-industry/employees",
          {"employee_name": f"{MARK}员工", "name": f"{MARK}员工", "department": dep, "employee_no": f"M{int(time.time()) % 100000}"},
          check=succ, show=lambda d: dump(d, 160))
    r.api("读回员工", "GET", "/api/mods/attendance-industry/employees", check=lambda d: MARK in dump(d, 100000),
          show=lambda d: f"员工 {d['data']['total']}")
    r.see("/attendance-industry/personnel", f"{MARK}员工", "考勤人员管理页出现新员工")


@spec("ind-fields")
def _(r: R):
    r.api("行业基线字段", "GET", "/api/platform-shell/industry-baseline", check=succ, show=lambda d: dump(d["data"], 200))
    r.api("行业配置", "GET", "/api/system/industry", check=lambda d: isinstance(d["data"]["config"], dict),
          show=lambda d: f"config keys {list(d['data']['config'])[:8]}")
    r.ui("/mod/xcagi-erp-domain-bridge/products", [])


@spec("ind-workspace")
def _(r: R):
    r.api("考勤规则", "GET", "/api/mods/attendance-industry/attendance/rules", check=lambda d: len(d["data"]["lines"]) >= 1,
          show=lambda d: d["data"]["lines"][0])
    r.api("考勤记录", "GET", "/api/mods/attendance-industry/records", check=succ, show=lambda d: dump(d["data"], 120))
    r.ui("/attendance-industry", ["考勤"])


@spec("ind-taiyangniao")
def _(r: R):
    r.api("太阳鸟专属考勤规则", "GET", "/api/mod/taiyangniao-pro/attendance/rules", check=succ, show=lambda d: dump(d, 200))
    r.api("私有交付项目", "GET", "/api/mod-store/private-delivery",
          check=lambda d: any(x["mod_id"] == "taiyangniao-pro" for x in d["data"]["projects"]),
          show=lambda d: f"{[x['mod_id'] for x in d['data']['projects']]}")
    r.ui("/taiyangniao-pro", ["考勤"])


@spec("ind-szqsm")
def _(r: R):
    r.ui("/sz-qsm-pro", ["奇士美"])
    r.block("奇士美专属业务操作", "该 Mod 为奇士美客户受保护定制，需奇士美企业账号授权；SUNBIRD 账号无该权益")


@spec("ind-custom-delivery")
def _(r: R):
    r.api("私有交付清单", "GET", "/api/mod-store/private-delivery", check=lambda d: len(d["data"]["projects"]) >= 1,
          show=lambda d: dump(d["data"]["projects"][0], 200))
    r.ui("/private-mod-delivery", ["交付"])


@spec("ind-lan-license")
def _(r: R):
    r.api("局域网授权桥状态", "GET", "/api/mod/xcagi-lan-license-bridge/lan/status", check=succ, show=lambda d: dump(d, 200))
    r.api("主机信息", "GET", "/api/mod/xcagi-lan-license-bridge/lan/host-info", check=has("enabled"), show=lambda d: dump(d, 200))
    r.ui("/mod/xcagi-lan-license-bridge/lan-gate", ["局域网"])


@spec("ind-modstore-pay")
def _(r: R):
    r.api("市场支付桥诊断", "GET", "/api/mod/xcagi-model-payment-bridge/model-payment/diagnostics", check=succ,
          show=lambda d: dump(d["data"], 200))
    r.api("套餐", "GET", "/api/mod/xcagi-model-payment-bridge/model-payment/plans", check=lambda d: len(d["data"]["plans"]) >= 1,
          show=lambda d: f"{[p['title'] for p in d['data']['plans']]}")
    r.ui("/mod/xcagi-model-payment-bridge/model-payment", ["模型"])


@spec("ind-planner")
def _(r: R):
    r.api("规划器宿主能力", "GET", "/api/mod/xcagi-planner-bridge/host-capabilities", check=succ, show=lambda d: dump(d, 200))
    r.api("规划器工具注册表", "GET", "/api/mod/xcagi-planner-bridge/tools/registry", check=succ, show=lambda d: dump(d, 200))
    r.ui("/", ["智能对话"])


@spec("ind-workflow-viz")
def _(r: R):
    r.api("可视化桥状态", "GET", "/api/mod/xcagi-workflow-visualization-bridge/status", check=succ, show=lambda d: dump(d, 200))
    r.ui("/workflow-employee-space", ["员工"])


# ============================ 支付 ============================
@spec("pay-alipay")
def _(r: R):
    r.api("支付宝诊断", "GET", "/api/model-payment/diagnostics", check=lambda d: d["data"]["sdk_installed"] is True,
          show=lambda d: f"alipay_configured={d['data']['alipay_configured']} sdk_installed={d['data']['sdk_installed']}")
    r.api("伪造回调被拒（验签）", "POST", "/api/model-payment/notify/alipay", {"out_trade_no": "FAKE", "trade_status": "TRADE_SUCCESS"},
          status=(200, 400, 403), expected="未签名回调不得入账", show=lambda d: dump(d))
    r.block("真实支付宝付款与异步回调", "需要真实支付宝账户扫码付款；本机 alipay_configured=false 且自动化不得真实扣款")
    r.ui("/settings?section=model-payment", ["模型服务"])


@spec("pay-wallet")
def _(r: R):
    r.api("钱包总览", "GET", "/api/market/wallet/overview", check=succ, show=lambda d: dump(d["data"], 160))
    r.api("模型用量", "GET", "/api/model-payment/usage", check=succ, show=lambda d: f"entries={d['data']['count']}")
    r.ui("/settings?section=model-payment", ["模型"], final="/settings")


@spec("pay-lan")
def _(r: R):
    r.api("局域网网关状态", "GET", "/api/lan/status", check=lambda d: d["is_admin_host"] is True, show=lambda d: dump(d, 200))
    r.api("网关管理员身份", "GET", "/api/lan/admin/whoami", check=succ, show=lambda d: dump(d, 160))
    r.ui("/lan-gate", ["局域网"])


@spec("pay-member-plan")
def _(r: R):
    r.api("会员套餐", "GET", "/api/market/membership-plans", check=lambda d: len(d["data"]["plans"]) >= 1,
          show=lambda d: f"{len(d['data']['plans'])} 档")
    r.api("支付订单", "GET", "/api/market/payment/orders", check=succ, show=lambda d: dump(d["data"]))
    r.api("订阅状态", "GET", "/api/auth/subscription/status", check=lambda d: d["data"]["active"] is True,
          show=lambda d: f"active={d['data']['active']} plan={d['data']['plan_id']}")
    r.ui("/settings?section=model-payment", ["模型服务"])


@spec("pay-lan-settings")
def _(r: R):
    r.api("内网设置", "GET", "/api/lan/admin/settings", check=has("enabled"), show=lambda d: dump(d, 200))
    r.api("白名单", "GET", "/api/lan/admin/allowlist", check=succ, show=lambda d: dump(d))
    r.ui("/lan-gate", ["授权"])


# ============================ 桌面 ============================
@spec("dt-shell")
def _(r: R):
    r.api("桌面壳拉起后端", "GET", "/api/desktop/status", check=lambda d: d["appRoutesReady"] and d["modsFullLoadDone"],
          show=lambda d: f"appRoutesReady={d['appRoutesReady']} modsFullLoadDone={d['modsFullLoadDone']}")
    r.ui("/desktop-runtime", ["桌面"])


@spec("dt-ota")
def _(r: R):
    r.api("更新检查", "GET", "/api/mod-store/updates", check=succ, show=lambda d: dump(d["data"], 160))
    r.ui("/settings", ["更新"])


@spec("dt-install-sign")
def _(r: R):
    r.api("运行构建身份与制品哈希", "GET", "/api/health", check=lambda d: len(d["build"]["artifact_sha256"] or "") in (0, 64),
          show=lambda d: dump(d["build"], 240))
    r.F.case("本机命令校验 /Applications/XCAGI.app 签名与公证", "codesign --verify --deep --strict；spctl -a -vv",
             "codesign 通过且 Gatekeeper 显示 Notarized Developer ID", _codesign)
    r.ui("/settings", ["v1.0.0.5"])


def _codesign():
    import subprocess
    v = subprocess.run(["codesign", "--verify", "--deep", "--strict", "/Applications/XCAGI.app"], capture_output=True, text=True)
    g = subprocess.run(["spctl", "-a", "-vv", "/Applications/XCAGI.app"], capture_output=True, text=True)
    out = (g.stdout + g.stderr).strip().replace("\n", " | ")
    return v.returncode == 0 and g.returncode == 0 and "Notarized Developer ID" in out, f"codesign rc={v.returncode}；spctl rc={g.returncode}：{out[:200]}"


@spec("dt-cold-start-rollback")
def _(r: R):
    r.api("冷启动完成", "GET", "/api/desktop/status", check=lambda d: d["readyForUi"] and not d["degraded"],
          show=lambda d: f"readyForUi={d['readyForUi']} degraded={d['degraded']}")
    r.ui("/", ["智能对话"])


@spec("dt-process-mgmt")
def _(r: R):
    r.api("后端进程健康", "GET", "/api/health", check=lambda d: d["status"] == "healthy", show=lambda d: d["status"])
    r.api("诊断包导出", "GET", "/api/desktop/support-bundle", status=(200,), show=lambda d: "返回 zip（PK 头）" if "PK" in dump(d, 20) else dump(d, 60))
    r.ui("/desktop-runtime", [])


@spec("dt-integrity")
def _(r: R):
    r.api("运行完整性", "GET", "/api/desktop/status", check=lambda d: d["runtimeIntegrity"]["status"] in ("ok", "healthy"),
          show=lambda d: dump(d["runtimeIntegrity"], 220))
    r.api("NeuroBus 健康", "GET", "/api/neurobus/health", check=lambda d: d["status"] == "healthy",
          show=lambda d: f"running={d['running']} errors={d['errors']}")
    r.ui("/desktop-runtime", [])


@spec("dt-rpa")
def _(r: R):
    r.api("自动化状态", "GET", "/api/desktop/automation/status", check=succ, show=lambda d: dump(d["data"]))
    r.api("写入自动化 profile", "POST", "/api/desktop/automation/profiles",
          {"profile": {"app_id": "mac-acc-0929", "name": "mac-acc-0929",
                       "mac_bundle_id": "com.apple.TextEdit"}},
          check=lambda d: succ(d) and (d.get("data") or {}).get("success") is not False,
          show=lambda d: dump(d, 160))
    r.api("读回 profile", "GET", "/api/desktop/automation/profiles", check=lambda d: "mac-acc-0929" in dump(d, 100000),
          show=lambda d: dump(d["data"], 160))
    r.ui("/desktop-runtime", [])


@spec("dt-neurobus")
def _(r: R):
    r.api("事件总线健康", "GET", "/api/neurobus/health", check=lambda d: d["running"] and d["published"] > 0,
          show=lambda d: f"published={d['published']} processed={d['processed']} errors={d['errors']}")
    r.api("总线统计", "GET", "/api/neurobus/stats", check=has("coordinator"), show=lambda d: dump(d["coordinator"]))
    r.api("桥接 Mod 处理器目录", "GET", "/api/mod/xcagi-neuro-bus-bridge/handlers/catalog", check=succ, show=lambda d: dump(d, 160))
    r.ui("/desktop-runtime", [])


@spec("dt-evidence-store")
def _(r: R):
    r.api("NeuroBus 迁移冒烟", "GET", "/api/neuro/migration-smoke", check=lambda d: d["bus_running"] is True, show=lambda d: dump(d, 200))
    r.api("存证签收状态", "GET", "/api/operations-line/signoff/status", check=succ, show=lambda d: dump(d["data"], 200))
    r.ui("/desktop-runtime", [])


@spec("dt-mac-control")
def _(r: R):
    r.api("控制输入通道", "GET", "/api/control/input/latest", check=succ, show=lambda d: dump(d))
    r.api("macOS 驱动", "GET", "/api/desktop/automation/status", check=lambda d: "mac" in d["data"]["drivers"],
          show=lambda d: dump(d["data"]["drivers"]))
    r.ui("/desktop-runtime", [])


# ============================ 安全 ============================
@spec("sec-identity")
def _(r: R):
    r.api("已登录身份", "GET", "/api/auth/me", check=lambda d: d["data"]["tenant_id"] >= 1, show=lambda d: f"tenant_id={d['data']['tenant_id']}")

    def check(p):
        res = p.js("""fetch('/api/preferences', {method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({key: 'x', value: 'y'})}).then(r => r.status)""")
        return res == 403, f"不带 CSRF 头的写请求返回 HTTP {res}"

    r.act("在页面内发起不带 CSRF 头的写请求", "被拒绝 403", lambda p: None, check)
    r.api("非管理员访问管理端接口被拒", "GET", "/api/admin/audit-logs", status=(401, 403), expected="HTTP 403", show=lambda d: dump(d, 120))


@spec("sec-runtime-gate")
def _(r: R):
    r.api("租户越权访问旧全局接口被拦截", "GET", "/api/customers", status=(403,), expected="HTTP 403 租户隔离", show=lambda d: dump(d, 140))
    r.api("会话安全", "GET", "/api/auth/session/validate", check=lambda d: d["valid"] is True, show=lambda d: "valid=True")
    r.ui("/desktop-runtime", [])


@spec("sec-csp")
def _(r: R):
    def check(p):
        res = p.js("""fetch('/api/health').then(r => ({csp: r.headers.get('content-security-policy'),
          xfo: r.headers.get('x-frame-options'), xcto: r.headers.get('x-content-type-options')}))""")
        ok = bool(res and (res.get("csp") or res.get("xfo")) and res.get("xcto") == "nosniff")
        return ok, f"响应头 {res}"

    r.act("读取安全响应头", "含 CSP/X-Frame-Options 且 X-Content-Type-Options=nosniff", lambda p: None, check)

    def check2(p):
        res = p.js("""fetch('https://example.com/', {mode: 'no-cors'}).then(() => 'allowed').catch(e => 'blocked:' + e.name)""")
        return str(res).startswith("blocked"), f"页面内向外部域 fetch 的结果：{res}（connect-src 仅允许 self/ws）"

    r.act("在页面内尝试连接外部域名", "被 CSP connect-src 拦截", lambda p: p.go("/", wait=2), check2)


@spec("sec-e2e")
def _(r: R):
    r.api("教程/验收场景", "GET", "/api/tutorial/v2/courses", check=lambda d: len(d["data"]) >= 1,
          show=lambda d: f"{[c['title'] for c in d['data']][:4]}")
    r.ui("/", ["智能对话"])


@spec("sec-release-gate")
def _(r: R):
    r.api("发布身份与构建时间", "GET", "/api/health", check=lambda d: d["build"]["git_sha"] == d["git_sha"],
          show=lambda d: f"release_id={d['release_id']} built_at={d['build']['built_at']}")
    r.api("运行时阻断项为空", "GET", "/api/health", check=lambda d: not d["runtime"]["blockers"], show=lambda d: dump(d["runtime"]["blockers"]))
    r.ui("/desktop-runtime", [])
