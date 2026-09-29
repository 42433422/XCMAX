"""ai-employee-publish（员工打包与发布）Web 管理端真机验收用例。

impl 参考：FHD/app/fastapi_routes/workflow_definitions.py（员工包/发布相关编排）。
真实验证面：办公员工包目录（/api/mod/xcagi-office-employee-pack-bridge/catalog）、
本机已安装员工包清单（/api/mod/xcagi-office-employee-pack-bridge/installed）、
员工包配置预览（/api/mods/employee-packs/{pack_id}/config-preview，打包物 manifest）。
管理端 UI：/admin/private-mod-delivery（生产员工 · 私有交付：制作→测试→验收→交付）。
"""

FEATURE = "ai-employee-publish"
ENTRY = "/admin/login"
VISIBLE_CONTENT = (
    "真实浏览器（Chromium，真实鼠标键盘）在自托管 Web 管理端建立管理员会话后："
    "读取办公员工包目录（pack_id 清单）→ 读取本机已安装员工包清单 → "
    "读取员工包配置预览（config_v2 认知模型与系统提示）→ "
    "不存在的员工包被拒（success=false 未安装）；并真实渲染私有交付生产中心。"
)


def _api(page, path, method="GET", body=None):
    return page.evaluate(
        """async ([p, m, b]) => {
            try {
                const init = {method: m, credentials: 'include', headers: {}};
                if (b !== null && b !== undefined) {
                    init.headers['Content-Type'] = 'application/json';
                    init.body = JSON.stringify(b);
                }
                if (m !== 'GET' && m !== 'HEAD') {
                    const cm = document.cookie.match(/(?:^|;\\s*)csrf_token=([^;]+)/);
                    if (cm) init.headers['X-CSRF-Token'] = decodeURIComponent(cm[1]);
                }
                const r = await fetch(p, init);
                const t = await r.text();
                let j = null; try { j = JSON.parse(t); } catch (e) {}
                return {status: r.status, body: j !== null ? j : t.slice(0, 300)};
            } catch (e) { return {status: 0, body: String(e)}; }
        }""",
        [path, method, body],
    )


def case_pack_catalog(page, env):
    r = _api(page, "/api/mod/xcagi-office-employee-pack-bridge/catalog")
    d = (r.get("body") or {}).get("data") or {}
    ids = d.get("pack_ids") or []
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and int(d.get("pack_count") or 0) >= 1 and len(ids) >= 1)
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "pack_count": d.get("pack_count"), "collection": d.get("collection"),
            "pack_ids_sample": ids[:6]}, ok


def case_pack_installed(page, env):
    r = _api(page, "/api/mod/xcagi-office-employee-pack-bridge/installed")
    d = (r.get("body") or {}).get("data") or {}
    ok = (r["status"] == 200 and (r.get("body") or {}).get("success") is True
          and int(d.get("total_installed") or 0) >= 1)
    office = d.get("office_installed") or []
    return {"status": r["status"], "success": (r.get("body") or {}).get("success"),
            "total_installed": d.get("total_installed"),
            "office_installed_count": d.get("office_installed_count"),
            "office_sample": [x.get("pack_id") for x in office[:5]]}, ok


def case_pack_config_preview(page, env):
    r = _api(page, "/api/mods/employee-packs/excel-generate-employee/config-preview")
    b = r.get("body") or {}
    d = b.get("data") or {}
    cog = d.get("cognition_model") or {}
    ok = (r["status"] == 200 and b.get("success") is True
          and d.get("pack_id") == "excel-generate-employee"
          and d.get("has_employee_config_v2") is True and bool(cog))
    return {"status": r["status"], "success": b.get("success"), "pack_id": d.get("pack_id"),
            "has_employee_config_v2": d.get("has_employee_config_v2"),
            "cognition_model": cog,
            "system_prompt_preview": str(d.get("system_prompt_preview") or "")[:60]}, ok


def case_pack_config_missing_denied(page, env):
    r = _api(page, "/api/mods/employee-packs/verify-missing-pack/config-preview")
    b = r.get("body") or {}
    msg = str(b.get("error") or b.get("message") or "")
    ok = r["status"] == 200 and b.get("success") is False and "员工包未安装" in msg
    return {"status": r["status"], "success": b.get("success"), "error": msg}, ok


def case_pack_config_invalid_id_denied(page, env):
    r = _api(page, "/api/mods/employee-packs/__verify_missing__/config-preview")
    b = r.get("body") or {}
    msg = str(b.get("error") or b.get("message") or "")
    ok = r["status"] == 200 and b.get("success") is False and "员工包编号无效" in msg
    return {"status": r["status"], "success": b.get("success"), "error": msg}, ok


def case_private_delivery_page(page, env):
    page.goto(env["base"] + "/admin/private-mod-delivery", wait_until="domcontentloaded", timeout=45000)
    text = ""
    for _ in range(10):
        page.wait_for_timeout(2500)
        text = page.inner_text("body") or ""
        if "私有" in text and ("交付" in text or "Mod" in text):
            break
    page.screenshot(path=str(env["shot"] / "P-private-delivery.png"))
    ok = "私有 Mod 生产中心" in text or ("生产员工" in text and "交付" in text)
    return {"final_url": page.url, "has_production": "生产员工" in text,
            "has_delivery": "交付" in text, "text_head": text.replace("\n", " ")[:220]}, ok


CASES = [
    {"id": "P1", "title": "办公员工包目录真实读取",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-office-employee-pack-bridge/catalog。",
     "expected": "HTTP 200、success=true，pack_count>=1 且返回 pack_id 清单。",
     "run": case_pack_catalog},
    {"id": "P2", "title": "本机已安装员工包清单",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mod/xcagi-office-employee-pack-bridge/installed。",
     "expected": "HTTP 200、success=true，total_installed>=1。",
     "run": case_pack_installed},
    {"id": "P3", "title": "员工包配置预览（打包物 manifest）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mods/employee-packs/excel-generate-employee/config-preview。",
     "expected": "HTTP 200、success=true，pack_id 匹配且 has_employee_config_v2=true，带认知模型配置。",
     "run": case_pack_config_preview},
    {"id": "P4", "title": "不存在的员工包被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mods/employee-packs/verify-missing-pack/config-preview。",
     "expected": "success=false，提示员工包未安装或 manifest 不存在。",
     "run": case_pack_config_missing_denied},
    {"id": "P5", "title": "非法员工包编号被拒（负例/边界）",
     "input": "已建立的管理员会话。",
     "actions": "在页面上下文 fetch GET /api/mods/employee-packs/__verify_missing__/config-preview。",
     "expected": "success=false，提示员工包编号无效。",
     "run": case_pack_config_invalid_id_denied},
    {"id": "P6", "title": "私有交付生产中心页面真实渲染",
     "input": "已建立的管理员会话。",
     "actions": "浏览器导航 /admin/private-mod-delivery，等待渲染生产员工/私有交付。",
     "expected": "页面渲染生产员工私有交付（制作→测试→验收→交付）相关区块。",
     "run": case_private_delivery_page},
]

# 人工实际打开这些文件后的结论（未查看不得声明）。
VISIBLE_RESULTS = {
    "00-login-form.png": "管理端登录页「管理员登录」：左侧蓝色品牌栏「XCMAX 服务器后台 · 平台运维 / 服务器后台与自动化治理」；右侧账号框已填 admin、密码框为掩码，可点「登 录」。",
    "P-private-delivery.png": "登录后进入「生产员工 · 私有交付」：标题「客户私有 Mod 生产中心」，说明「制作 → 测试 → 验收 → 交付；不通过只能转返工，不能跨阶段跳跃」，含定制入口（说明你要的模块或员工 / 发起定制）与企业端未绑定市场账号的红色提示，证明员工包/Mod 打包发布生产面真实渲染。",
    "__video__": "本轮真实浏览器会话录像（webm，13.00s，1600x1000，ffmpeg 实测）：管理员登录 → 员工包目录 → 已安装清单 → 配置预览 → 缺失包/非法编号被拒 → 私有交付页渲染。",
}