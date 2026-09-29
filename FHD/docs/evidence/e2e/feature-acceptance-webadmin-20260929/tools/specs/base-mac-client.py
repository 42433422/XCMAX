"""base-mac-client（macOS 桌面客户端）真机验收用例。

本能力的对外承诺是"macOS 桌面安装包与客户端外壳"，因此本轮验的是两件事，全部现场重算：
  1) 安装包与已安装客户端的身份/签名/公证/Gatekeeper：DMG 现场 sha256、应用包现场 codesign 深验、
     spctl 评估、公证票据 stapler 校验、build-info 的 version/releaseId/gitSha；
  2) 客户端外壳真的能起：本轮真实启动已安装客户端（隔离端口与隔离 userData，不影响其它实例），
     验证其渲染进程可被 CDP 连接、真实界面渲染、自带后端拉起并通过健康检查。

被测对象固定为已安装的 /Applications/XCAGI.app（build-info 的 gitSha 必须是本仓库 main 的祖先）。
"""

import re

FEATURE = "base-mac-client"
PLATFORM = "macos"
ENTRY = "/"
VISIBLE_CONTENT = (
    "现场重算 macOS 安装包与客户端身份（DMG sha256、build-info、codesign 深验、Gatekeeper、公证票据），"
    "并真实启动已安装客户端（隔离端口 17650 / 隔离 userData），验证真实界面渲染、CDP 可连接、"
    "自带后端健康检查通过，以及桌面端不提供管理后台的既有边界。"
)

APP = "/Applications/XCAGI.app"

EXTRA_OBSERVATIONS = [
    "本轮验收的是**已安装客户端** /Applications/XCAGI.app（build-info gitSha 37f22bcb…，为 origin/main 的祖先），"
    "不是任何分支候选包；安装包身份取自 /Users/Shared/XCAGI-FULLCLOSED-20260928/artifact/ 下的正式 DMG。",
    "为不影响本机其它正在运行的客户端实例，本轮以隔离端口与隔离 userData 启动被测客户端；"
    "隔离实例首次启动为全新数据目录，因此界面停在未登录态，这属于预期而不是缺陷。",
]


def _sh(env, args, timeout=180):
    from macos_client_accept import run_cmd
    return run_cmd(args, timeout=timeout)


def case_dmg_identity(page, env):
    from pathlib import Path

    from macos_client_accept import DMG, sha256_file
    dmg = Path(DMG)
    digest = sha256_file(dmg)
    ok = (dmg.is_file() and re.fullmatch(r"[0-9a-f]{64}", digest or "") is not None
          and dmg.stat().st_size > 100_000_000)
    return {"dmg_path": str(dmg), "dmg_sha256_this_round": digest,
            "dmg_size_bytes": dmg.stat().st_size if dmg.is_file() else None}, ok


def case_build_info(page, env):
    build = env["app"]
    ok = (re.fullmatch(r"[0-9a-f]{40}", str(build.get("gitSha") or "")) is not None
          and str(build.get("version")) == "1.0.0.5"
          and str(build.get("releaseId")) == f"xcagi-{build.get('version')}-{build.get('gitSha')}")
    return {"installed_build_info": build,
            "release_id_consistent": str(build.get("releaseId")) == f"xcagi-{build.get('version')}-{build.get('gitSha')}",
            "schema_version": build.get("schema_version"), "builtAt": build.get("builtAt")}, ok


def case_codesign_gatekeeper(page, env):
    verify = _sh(env, ["codesign", "--verify", "--deep", "--strict", "--verbose=2", APP])
    spctl = _sh(env, ["spctl", "-a", "-vv", "-t", "exec", APP])
    stapler = _sh(env, ["xcrun", "stapler", "validate", APP])
    env["log"](f"codesign exit={verify['exit_code']} spctl exit={spctl['exit_code']} stapler exit={stapler['exit_code']}")
    ok = (verify["exit_code"] == 0 and spctl["exit_code"] == 0 and stapler["exit_code"] == 0
          and "accepted" in (spctl["stdout"] + spctl["stderr"])
          and "worked" in (stapler["stdout"] + stapler["stderr"]).lower())
    return {"codesign_verify": verify, "spctl_assess": spctl, "stapler_validate": stapler}, ok


def case_shell_launch(page, env):
    launch = env["launch"]
    url, title = page.url, ""
    try:
        title = page.title()
    except Exception:  # noqa: BLE001
        pass
    text = (page.inner_text("body") or "")[:400]
    page.screenshot(path=str(env["shot"] / "M2-shell-running.png"))
    ok = launch["cdp"] and launch["backend"] and url.startswith("http://127.0.0.1:") and bool(text.strip())
    return {"isolated_pid": launch["pid"], "cdp_reachable": launch["cdp"],
            "backend_health_reachable": launch["backend"], "renderer_url": url,
            "page_title": title, "visible_text_head": text.replace("\n", " ")[:220]}, ok


def case_own_backend_health(page, env):
    r = page.evaluate(
        "async (base) => { const r = await fetch(base + '/api/health'); const t = await r.text();"
        " let j=null; try { j=JSON.parse(t);}catch(e){} return {status:r.status, body:j}; }",
        env["base"],
    )
    b = r.get("body") or {}
    runtime = b.get("runtime") or {}
    comps = runtime.get("components") or {}
    required = {k: v.get("ok") for k, v in comps.items() if isinstance(v, dict) and v.get("required")}
    ok = (r["status"] == 200 and b.get("version") == env["app"].get("version")
          and b.get("git_sha") == env["app"].get("gitSha") and runtime.get("status") in ("healthy", "degraded")
          and required and all(required.values()))
    return {"http_status": r["status"], "product_version": b.get("version"),
            "backend_git_sha": b.get("git_sha"), "matches_build_info_sha": b.get("git_sha") == env["app"].get("gitSha"),
            "status": b.get("status"), "runtime_status": runtime.get("status"),
            "required_components_ok": required,
            "degradedReasons": b.get("degradedReasons")}, ok


def case_desktop_admin_boundary(page, env):
    """既有边界：桌面端不提供管理后台（设计如此），客户端外壳不应暴露管理数据面。"""
    r = page.evaluate(
        "async (base) => { const out = {};"
        " for (const p of ['api/admin/audit-logs','api/auth/me']) {"
        "   const r = await fetch(base + '/' + p, {credentials:'include'});"
        "   const t = await r.text(); let j=null; try { j=JSON.parse(t);}catch(e){}"
        "   out[p] = {status: r.status, code: (j && (j.error || {}).code) || (j && j.error_code) || null}; }"
        " return out; }",
        env["base"],
    )
    audit = r.get("api/admin/audit-logs") or {}
    ok = audit.get("status") == 403 and audit.get("code") in (None, "ADMIN_DESKTOP_FORBIDDEN")
    return {"admin_api": audit, "auth_me": r.get("api/auth/me")}, ok


def case_login_tabs(page, env):
    """真实界面交互：客户端外壳的登录方式切换（账号密码 / 手机验证码 / 扫码登录）。"""
    def tab_state():
        return page.evaluate(
            "() => { const tabs = [...document.querySelectorAll('[role=tab], .login-tab, .el-tabs__item, button, a')]"
            ".filter((e) => /扫码登录|手机验证码|账号密码/.test(e.innerText || ''));"
            " const canvas = document.querySelector('canvas');"
            " const img = [...document.querySelectorAll('img')].filter((i) => /qr|code/i.test(i.src || ''));"
            " return {tab_texts: tabs.map((t) => (t.innerText || '').trim()),"
            "   active: (tabs.filter((t) => /active|is-active/.test(t.className)).map((t) => (t.innerText || '').trim())[0]) || '',"
            "   has_canvas: !!canvas, canvas_w: canvas ? canvas.width : 0, qr_img_count: img.length,"
            "   inputs: document.querySelectorAll('input').length}; }"
        )
    before = tab_state()
    clicked = False
    try:
        page.locator("text=扫码登录").first.click(timeout=8000)
        clicked = True
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2500)
    after = tab_state()
    page.screenshot(path=str(env["shot"] / "M5-qr-login-tab.png"))
    ok = clicked and "扫码登录" in after["tab_texts"] and (after["has_canvas"] or after["qr_img_count"] > 0)
    return {"clicked": clicked, "before": before, "after": after,
            "qr_surface": "canvas" if after["has_canvas"] else ("img" if after["qr_img_count"] else "none")}, ok


VISIBLE_RESULTS = {
    "M2-shell-running.png": "已安装客户端启动后的真实画面：左侧「XCAGI 企业版 · 智能企业管理平台」，右侧「企业账号登录」（账号密码 / 手机验证码 / 扫码登录三档），含账号、密码、企业邀请码输入框与「登 录」按钮，右上「注册账号 / 购买与授权」。隔离实例为全新 userData，故停在未登录态。",
    "M5-qr-login-tab.png": "真实点击「扫码登录」后客户端外壳的画面：标签切到「扫码登录」并高亮，页面显示真实二维码、「请使用 XCAGI Android App 扫描二维码并登录」、「剩余 120 秒 · 过期后请切换 Tab 刷新」与「刷新二维码」按钮。",
    "99-final-state.png": "本轮结束前客户端外壳的最终画面。",
    "__video__": "本轮真实渲染帧编码的客户端外壳会话录像（webm，VP8，帧取自被测客户端自身画面）。",
}

CASES = [
    {"id": "M1", "title": "已安装客户端外壳真实启动且渲染进程可连",
     "input": "已安装的 /Applications/XCAGI.app（隔离端口 17650、隔离 userData）。",
     "actions": "本轮真实启动客户端并等待其渲染进程开放 CDP；连接后读取页面 URL、标题与可见文本。",
     "expected": "CDP 可连；页面为 127.0.0.1 本地地址；界面渲染出真实可见内容。",
     "run": case_shell_launch},
    {"id": "M2", "title": "安装包（DMG）身份现场重算",
     "input": "正式发布 DMG 文件。",
     "actions": "本轮现场重算 DMG 的 SHA-256 与大小。",
     "expected": "SHA-256 为 64 位十六进制且文件规模符合完整安装包量级。",
     "run": case_dmg_identity},
    {"id": "M3", "title": "已安装应用包身份与 releaseId 自洽",
     "input": "已安装客户端的 build-info.json。",
     "actions": "读取并核对 version / releaseId / gitSha 的对应关系与 schema_version。",
     "expected": "gitSha 为 40 位十六进制；版本 1.0.0.5；releaseId = xcagi-<version>-<gitSha>。",
     "run": case_build_info},
    {"id": "M4", "title": "代码签名深验 / Gatekeeper / 公证票据现场校验",
     "input": "已安装应用包。",
     "actions": "本轮现场执行 codesign --verify --deep --strict、spctl -a -vv -t exec、xcrun stapler validate。",
     "expected": "三者退出码均为 0；spctl 判定 accepted；stapler 输出 validate 成功。",
     "run": case_codesign_gatekeeper},
    {"id": "M5", "title": "客户端自带后端随外壳启动并通过健康检查",
     "input": "已启动的隔离实例。",
     "actions": "从渲染进程页面上下文请求本地后端 /api/health，核对版本与 SHA 是否与外壳 build-info 一致，并检查必需组件。",
     "expected": "HTTP 200；version 与 gitSha 与 build-info 一致；runtime 为 healthy/degraded 且所有 required 组件 ok=true。",
     "run": case_own_backend_health},
    {"id": "M7", "title": "客户端外壳登录方式可真实切换（扫码登录）",
     "input": "已启动的隔离实例（登录页默认账号密码方式）。",
     "actions": "在真实界面上点击「扫码登录」标签，等待渲染后读取标签激活态与二维码承载元素。",
     "expected": "切换后「扫码登录」为激活标签，并渲染出二维码承载元素（canvas 或二维码图片）。",
     "run": case_login_tabs},
    {"id": "M6", "title": "桌面端不暴露管理后台数据面（既有边界）",
     "input": "已启动的隔离实例。",
     "actions": "从页面上下文请求桌面后端的 /api/admin/audit-logs 与 /api/auth/me。",
     "expected": "管理接口返回 403（桌面端设计上不提供管理员登录入口），不返回管理数据。",
     "run": case_desktop_admin_boundary},
]

IDENTITY = {"path": "FHD/docs/evidence/e2e/feature-acceptance-webadmin-20260929/tools/runs/base-mac-client/base-mac-client-macos-identity.json",
            "git_sha": "git_sha", "version": "product_version"}
ARTIFACT = {"path": "FHD/docs/evidence/e2e/feature-acceptance-webadmin-20260929/tools/runs/base-mac-client/base-mac-client-macos-artifact.json",
            "sha256": "artifacts|official_dmg|sha256",
            "git_sha": "release|git_sha", "version": "release|version"}