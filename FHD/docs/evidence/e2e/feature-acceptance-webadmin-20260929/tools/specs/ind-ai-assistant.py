"""ind-ai-assistant（行业 AI 助手）Web 管理端真机验收用例。

目录（catalog）状态：placeder/planned —— name「行业 AI 助手（占位）」，evidence.impl = []，
summary「行业专属 AI 助手，当前为占位，尚未有已合入实现」。
历史取证（FHD/docs/evidence/e2e/macos-features-100-1.0.0.5/records/ind-ai-assistant.json）：
catalog_status=planned、method=planned、notes=「目录状态为『规划中』，尚无实现，无法进行真机验证」。

本轮真机核对（真实浏览器会话内 fetch）：
  * 候选「行业 AI 助手」路由全部 404：GET /api/mods/coating-industry/assistant、
    GET /api/ai/assistant（资源不存在）。
  * 行业配置 /api/system/industry/涂料 的 subsystems 仅有 products/customers/orders/shipment-records，
    无任何 assistant 相关子系统；Mod 注册表（63 项）无「行业 AI 助手」条目。
  * 平台确实存在通用 AI 助手底座（/api/ai/test 200「AI 聊天服务运行正常」、
    /api/ai/kitten/business-snapshot 200 生成经营分析文本），但非「行业专属」。

结论：本环境无「行业 AI 助手」真实可验证面 → 核心用例如实判为失败（未实现/未验证），不做假 PASS。
"""

import html as _html
import json as _json

FEATURE = "ind-ai-assistant"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium）在自托管 Web 管理端建立管理员会话后核对「行业 AI 助手」能力面："
    "候选行业助手路由 /api/mods/coating-industry/assistant 与 /api/ai/assistant 均 404、"
    "行业配置无 assistant 子系统、Mod 注册表无行业助手条目 → 本环境无真实可验证面（未实现），核心用例失败；"
    "平台通用 AI 助手底座真实可用（/api/ai/test 200、/api/ai/kitten/business-snapshot 200 生成分析文本），但非行业专属。"
)


def _api(page, path):
    return page.evaluate(
        "async (p) => { try { const r = await fetch(p, {credentials:'include'});"
        " const t = await r.text(); let j=null; try { j=JSON.parse(t); } catch(e) {}"
        " return {status:r.status, body: j!==null?j:t.slice(0,400)}; }"
        " catch(e){ return {status:0, body:String(e)}; } }", path)


def _card(page, env, name, cid, title, rows):
    payload = _json.dumps(rows, ensure_ascii=False, default=str)
    if len(payload) > 3400:
        payload = payload[:3400] + " …(截断)"
    page.set_content(
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><style>"
        "body{margin:0;padding:22px;background:#0b1b2b;color:#e8f1fb;font:13px/1.7 -apple-system,'Segoe UI',sans-serif}"
        "h1{font-size:15px;margin:0 0 4px}.sub{color:#8fb3d9;font-size:12px;margin-bottom:14px}"
        ".card{background:#122b45;border:1px solid #21405f;border-radius:10px;padding:16px}"
        "pre{background:#08131f;border-radius:8px;padding:12px;white-space:pre-wrap;word-break:break-all;color:#9ee6a3;font-size:12px}"
        "</style></head><body>"
        f"<h1>{cid} · {_html.escape(title)}</h1>"
        "<div class='sub'>XCMAX 服务器后台 · 真实浏览器本轮 fetch 观测（内容为本轮真实响应，非构造）</div>"
        f"<div class='card'><pre>{_html.escape(payload)}</pre></div></body></html>")
    page.screenshot(path=str(env["shot"] / name))


def case_industry_assistant_surface(page, env):
    coating_asst = _api(page, "/api/mods/coating-industry/assistant")
    ai_asst = _api(page, "/api/ai/assistant")
    industry = page.evaluate(
        "async () => { const p='/api/system/industry/'+encodeURIComponent('涂料');"
        " try { const r=await fetch(p,{credentials:'include'}); const t=await r.text(); let j=null; try{j=JSON.parse(t);}catch(e){}"
        " return {status:r.status, body:j!==null?j:t.slice(0,300)}; } catch(e){ return {status:0, body:String(e)}; } }")
    cfg = ((industry.get("body") or {}).get("data") or {}).get("config") or {}
    subs = list((cfg.get("subsystems") or {}).keys())
    asst_keys = [k for k in cfg.keys() if "assist" in k.lower()]
    mods = (_api(page, "/api/mods").get("body") or {}).get("data") or []
    asst_mods = [m.get("id") for m in mods if "assistant" in str(m.get("id", "")).lower() or "assist" in str(m.get("name", "")).lower()]
    # 期望：存在行业专属 AI 助手真实能力面（路由 200 或行业配置含 assistant 子系统）
    ok = (coating_asst["status"] == 200 or ai_asst["status"] == 200 or bool(asst_keys))
    _card(page, env, "A1-industry-assistant-probe.png", "A1",
          "核心：行业 AI 助手能力面存在性核对（本环境无可验证面 → 失败）", {
              "GET /api/mods/coating-industry/assistant": {"status": coating_asst["status"],
                                                           "message": (coating_asst.get("body") or {}).get("message")},
              "GET /api/ai/assistant": {"status": ai_asst["status"],
                                        "message": (ai_asst.get("body") or {}).get("message")},
              "GET /api/system/industry/涂料": {"status": industry["status"], "subsystems": subs,
                                                 "assistant_keys": asst_keys},
              "Mod 注册表 assistant 条目": asst_mods,
              "verdict": "无行业专属 AI 助手路由/配置/Mod → 目录状态 planned，尚无实现，核心用例未验证",
          })
    return {"coating_assistant": {"status": coating_asst["status"]},
            "ai_assistant": {"status": ai_asst["status"]},
            "industry_subsystems": subs, "assistant_keys": asst_keys,
            "assistant_mods": asst_mods,
            "unverified_reason": "catalog planned; no industry-ai-assistant route/config/mod"}, ok


def case_generic_ai_assistant(page, env):
    t = _api(page, "/api/ai/test")
    k = _api(page, "/api/ai/kitten/business-snapshot")
    tb = t.get("body") or {}
    kb = k.get("body") or {}
    kd = kb.get("data") or {}
    ok = (t["status"] == 200 and "AI" in str(tb.get("message"))
          and k["status"] == 200 and kd.get("success") is True and bool(str(kd.get("text") or "").strip()))
    _card(page, env, "A2-generic-ai-base.png", "A2",
          "平台通用 AI 助手底座真实可用（非行业专属）", {
              "GET /api/ai/test": {"status": t["status"], "message": tb.get("message")},
              "GET /api/ai/kitten/business-snapshot": {
                  "status": k["status"], "success": kd.get("success"),
                  "stats_keys": list((kd.get("stats") or {}).keys()),
                  "text_head": str(kd.get("text") or "")[:220]},
          })
    return {"ai_test": {"status": t["status"], "message": tb.get("message")},
            "kitten_snapshot": {"status": k["status"], "success": kd.get("success")}}, ok


def case_unknown_ai_route(page, env):
    r = _api(page, "/api/mods/coating-industry/assistant")
    b = r.get("body") or {}
    ok = r["status"] == 404
    return {"status": r["status"], "message": b.get("message")}, ok


VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「XCMAX 服务器后台 · 管理员登录」，账号框已填 admin、密码框为掩码。",
    "A1-industry-assistant-probe.png": "卡片显示四项真实核对：GET /api/mods/coating-industry/assistant → {status:404,message:资源不存在：/api/mods/coating-industry/assistant}；GET /api/ai/assistant → {status:404,message:资源不存在：/api/ai/assistant}；GET /api/system/industry/涂料 → {status:200,subsystems:[products,customers,orders,shipment-records],assistant_keys:[]}；Mod 注册表 assistant 条目仅 [employee-interview-assistant]；verdict=无行业专属 AI 助手路由/配置/Mod → 目录状态 planned，尚无实现。核心用例失败（未验证）。",
    "A2-generic-ai-base.png": "卡片显示平台通用 AI 底座真实可用：GET /api/ai/test → {status:200,message:AI 聊天服务运行正常}；GET /api/ai/kitten/business-snapshot → {status:200,success:true,stats_keys:[materials_total,material_inventory_value_estimate,materials_low_stock_count,...,shipments_sample_amount_sum],text_head:\"说明：以下为当前业务数据库中的库存与出货快照…\"}。",
    "__video__": "本轮真实浏览器会话录像（webm，23.12s，ffmpeg 实测）：管理员登录 → 行业助手路由探测（404/404/无子系统）→ 通用 AI 底座 200 → 候选路由 404。",
}

CASES = [
    {"id": "A1", "title": "行业 AI 助手能力面存在性核对（核心，本轮未验证）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET 候选行业助手路由 /api/mods/coating-industry/assistant、/api/ai/assistant，"
                "并检查行业配置 subsystems 与 Mod 注册表。",
     "expected": "存在行业专属 AI 助手真实能力面（路由 200 或行业配置含 assistant 子系统）。",
     "run": case_industry_assistant_surface},
    {"id": "A2", "title": "平台通用 AI 助手底座真实可用（非行业专属）",
     "input": "已建立的管理员会话。",
     "actions": "页面上下文 GET /api/ai/test 与 /api/ai/kitten/business-snapshot。",
     "expected": "HTTP 200，返回 AI 服务运行正常与真实生成的分析文本。",
     "run": case_generic_ai_assistant},
    {"id": "A3", "title": "候选行业助手路由不存在（负例/边界）",
     "input": "同上。",
     "actions": "页面上下文 GET /api/mods/coating-industry/assistant。",
     "expected": "HTTP 404。",
     "run": case_unknown_ai_route},
]