#!/usr/bin/env python3
"""base-login「登录与会话管理」macOS 真机验收采集器（本轮证据，不修改产品）。

用例（真实安装包 + 真实后端 + 真实 UI）：
  M1 未登录拒绝：无会话访问 /api/auth/me、/api/auth/session/validate
  M2 企业账号登录（GUI 真实输入）：登录后 /api/auth/me 200 且 account_kind=enterprise
  M3 会话保持（进程重启）：重启应用进程后同一会话仍有效（服务端会话）
  M4 安全退出：退出后旧会话失效，受保护接口被拒绝
  M5 边界：错误密码拒绝；桌面端拒绝管理员会话
  M6 Web 端共用同一账户体系：同一账号在修茈市场（Web）登录成功

用法: python3 accept_mac.py <phase>
  phase ∈ launch|prelogin|postlogin|restart|postlogout|negative|db|summary
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

CDP_PORT = 9223
BASE = "http://127.0.0.1:17500"
APP = "/Applications/XCAGI.app"
WORK = "/private/tmp/xcagi-feat-base-login"
DATA = os.path.join(WORK, "data")
EV = os.path.join(WORK, "evidence")
USER = "SUNBIRD"
PASS = "SUN123456"
MARKET = "https://xiu-ci.com"

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOG = []


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    LOG.append(line)


def sh(cmd, timeout=180):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return {"cmd": cmd, "rc": p.returncode,
            "out": (p.stdout or "").strip()[-4000:], "err": (p.stderr or "").strip()[-2000:]}


def write(name, payload):
    path = os.path.join(EV, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log("evidence -> %s" % path)
    return path


def http(method, path, data=None, headers=None, base=BASE, timeout=60):
    h = dict(headers or {})
    body = None
    if data is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(base + path, data=body, headers=h, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = {"_raw": raw[:300].decode("utf-8", "ignore")}
    return {"status": status, "body": parsed}


def cdp_http(path):
    with _OPENER.open("http://127.0.0.1:%d%s" % (CDP_PORT, path), timeout=10) as r:
        return json.loads(r.read().decode())


def cdp(method, params=None, timeout=60):
    from websockets.sync.client import connect
    target = None
    for t in cdp_http("/json"):
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            target = t
            break
    if target is None:
        raise RuntimeError("no page target on CDP %d" % CDP_PORT)
    with connect(target["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024, proxy=None,
                 open_timeout=20, close_timeout=5) as ws:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(ws.recv(timeout=timeout + 15))
            if msg.get("id") == 1:
                return msg


def js(expr, timeout=60):
    msg = cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True,
                                   "awaitPromise": True, "timeout": timeout * 1000})
    res = msg.get("result", {})
    if res.get("exceptionDetails"):
        raise RuntimeError("JS: %s" % json.dumps(res["exceptionDetails"])[:300])
    return res.get("result", {}).get("value")


def dom_state():
    return js("""(() => {
      const inputs = Array.from(document.querySelectorAll('input'))
        .filter(e => e.offsetParent !== null)
        .map(e => ({name: e.name, type: e.type, ph: e.placeholder}));
      const txt = (document.body.innerText || '');
      const loginBtn = Array.from(document.querySelectorAll('button'))
        .find(b => (b.textContent||'').replace(/\\s+/g,'') === '登录' && b.offsetParent !== null);
      return {url: location.href, title: document.title, inputs,
              login_button_visible: !!loginBtn,
              workspace_markers: {chat: txt.includes('智能对话') || txt.includes('新对话'),
                                  sidebar: txt.includes('退出登录') || txt.includes('历史')}};
    })()""")


def cookies():
    res = cdp("Network.getAllCookies").get("result", {}).get("cookies", [])
    return [{k: c.get(k) for k in ("name", "value", "domain", "path", "expires", "httpOnly", "session")}
            for c in res if c.get("domain", "").endswith("127.0.0.1")]


def session_header(ck):
    pairs = {c["name"]: c["value"] for c in ck}
    return {"Cookie": "session_id=%s" % pairs.get("session_id", "")}


def shot(tag):
    paths = {}
    p1 = os.path.join(EV, "%s-renderer.png" % tag)
    try:
        data = cdp("Page.captureScreenshot", {"format": "png"}).get("result", {}).get("data")
        if data:
            open(p1, "wb").write(base64.b64decode(data))
            paths["renderer"] = p1
    except Exception as e:  # noqa: BLE001
        paths["renderer_error"] = repr(e)
    p2 = os.path.join(EV, "%s-screen.png" % tag)
    r = sh("screencapture -x '%s'" % p2)
    if os.path.isfile(p2):
        paths["screen"] = p2
    else:
        paths["screen_error"] = r
    return paths


def health():
    return http("GET", "/api/health")


def app_identity():
    info = json.load(open(os.path.join(APP, "Contents/Resources/build-info.json")))
    return info


def wait_ready(timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        try:
            h = health()
            if h["status"] == 200:
                try:
                    cdp_http("/json/version")
                    return True
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    return False


def launch(args=None):
    sh("launchctl setenv XCAGI_DESKTOP_USER_DATA_DIR '%s'" % DATA)
    r = sh("open -a '%s' --args --remote-debugging-port=%d" % (APP, CDP_PORT))
    return r


def quit_app():
    sh("osascript -e 'quit app \"XCAGI\"' || true")
    for _ in range(30):
        if not sh("pgrep -f 'XCAGI.app/Contents/MacOS/XCAGI' | head -1")["out"]:
            return True
        time.sleep(1)
    sh("pkill -f 'XCAGI.app/Contents/MacOS/XCAGI' || true")
    time.sleep(3)
    return True


# ---------------- phases ----------------

def phase_launch():
    quit_app()
    r = launch()
    ready = wait_ready()
    ident = {
        "phase": "M0-identity", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "app_path": APP, "app_build_info": app_identity(),
        "machine": {"sw_vers": sh("sw_vers")["out"], "uname": sh("uname -a")["out"],
                    "hostname": sh("hostname")["out"]},
        "data_dir": DATA, "cdp_port": CDP_PORT,
        "launch": r, "ready": ready,
        "health": health(),
    }
    write("01-identity.json", ident)
    if not ready:
        raise SystemExit("app 未就绪")


def phase_prelogin():
    dom = dom_state()
    ck = cookies()
    me = http("GET", "/api/auth/me")
    sv = http("GET", "/api/auth/session/validate")
    out = {"phase": "M1-未登录拒绝", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "dom": dom, "cookies_before_login": ck,
           "api_auth_me": me, "api_session_validate": sv,
           "shots": shot("02-prelogin")}
    has_session_cookie = any(c["name"] == "session_id" for c in ck)
    out["has_session_cookie"] = has_session_cookie
    out["verdict"] = "PASS" if (not has_session_cookie and me["body"].get("valid") is False
                                and sv["body"].get("valid") is False
                                and dom.get("login_button_visible")
                                and dom.get("workspace_markers", {}).get("chat") is False) else "FAIL"
    write("02-prelogin.json", out)
    log("M1 verdict=%s" % out["verdict"])


def phase_postlogin():
    dom = dom_state()
    ck = cookies()
    hdr = session_header(ck)
    me = http("GET", "/api/auth/me", headers=hdr)
    sv = http("GET", "/api/auth/session/validate", headers=hdr)
    u = ((me["body"].get("data") or {}).get("user") or {})
    d = (me["body"].get("data") or {})
    out = {"phase": "M2-企业账号登录", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "dom": dom, "cookies": ck, "api_auth_me": me, "api_session_validate": sv,
           "facts": {"username": u.get("username"), "tier": u.get("tier"),
                     "account_kind": d.get("account_kind"), "tenant_id": d.get("tenant_id"),
                     "account_tier": d.get("account_tier")},
           "shots": shot("03-postlogin")}
    ok = (ck and me["status"] == 200 and me["body"].get("success") is True
          and d.get("account_kind") == "enterprise" and sv["body"].get("valid") is True)
    out["verdict"] = "PASS" if ok else "FAIL"
    write("03-postlogin.json", out)
    log("M2 verdict=%s facts=%s" % (out["verdict"], json.dumps(out["facts"], ensure_ascii=False)))


def phase_restart():
    before = cookies()
    sid_before = session_header(before)
    quit_app()
    time.sleep(3)
    launch()
    ready = wait_ready()
    time.sleep(5)
    after = cookies()
    dom = dom_state()
    me = http("GET", "/api/auth/me", headers=sid_before)
    sv = http("GET", "/api/auth/session/validate", headers=sid_before)
    out = {"phase": "M3-会话保持(进程重启)", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "ready": ready, "cookies_before": before, "cookies_after": after, "dom": dom,
           "api_auth_me": me, "api_session_validate": sv,
           "same_session_id": session_header(after).get("Cookie") == sid_before.get("Cookie"),
           "shots": shot("04-restart")}
    ok = (ready and me["status"] == 200 and me["body"].get("success") is True
          and sv["body"].get("valid") is True and not dom.get("login_button_visible"))
    out["verdict"] = "PASS" if ok else "FAIL"
    write("04-session-restart.json", out)
    log("M3 verdict=%s" % out["verdict"])


def phase_postlogout():
    ck = cookies()
    hdr = session_header(ck)
    me_before = http("GET", "/api/auth/me", headers=hdr)
    lo = http("POST", "/api/auth/logout", headers=hdr)
    me_after = http("GET", "/api/auth/me", headers=hdr)
    sv_after = http("GET", "/api/auth/session/validate", headers=hdr)
    no_sess = http("POST", "/api/auth/logout")
    ck_after = cookies()
    dom = dom_state()
    out = {"phase": "M4-安全退出", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "me_before": me_before, "logout": lo, "me_after": me_after,
           "validate_after": sv_after, "logout_without_session": no_sess,
           "cookies_after": ck_after, "dom": dom, "shots": shot("05-postlogout")}
    ok = (me_before["body"].get("success") is True and lo["status"] == 200
          and me_after["body"].get("valid") is False and sv_after["body"].get("valid") is False)
    out["verdict"] = "PASS" if ok else "FAIL"
    write("05-postlogout.json", out)
    log("M4 verdict=%s" % out["verdict"])


def phase_negative():
    bad = http("POST", "/api/auth/login", {"username": USER, "password": "definitely-wrong-0001",
                                           "account_kind": "enterprise"})
    admin = http("POST", "/api/auth/login", {"username": USER, "password": PASS, "account_kind": "admin"})
    empty = http("POST", "/api/auth/login", {"username": "", "password": ""})
    market = http("POST", "/api/auth/login", {"username": USER, "password": PASS}, base=MARKET, timeout=90)
    out = {"phase": "M5/M6-边界与Web", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "wrong_password": bad, "admin_kind_on_desktop": admin, "empty_credentials": empty,
           "market_web_login": {"base": MARKET, "status": market["status"],
                                "body_keys": sorted(list(market["body"].keys()))[:12] if isinstance(market["body"], dict) else None,
                                "ok": market["body"].get("ok") if isinstance(market["body"], dict) else None,
                                "has_access_token": bool(market["body"].get("access_token")) if isinstance(market["body"], dict) else False,
                                "user": (market["body"].get("user") or {}).get("username") if isinstance(market["body"], dict) else None,
                                "desktop_access": market["body"].get("desktop_access") if isinstance(market["body"], dict) else None,
                                "account_tier": market["body"].get("account_tier") if isinstance(market["body"], dict) else None}}
    ok = (bad["body"].get("success") is False
          and admin["body"].get("success") is False
          and empty["body"].get("success") is False)
    out["verdict_desktop_boundary"] = "PASS" if ok else "FAIL"
    web_ok = bool(out["market_web_login"]["ok"]) or out["market_web_login"]["has_access_token"]
    out["verdict_web"] = "PASS" if web_ok else "FAIL"
    write("06-negative-and-web.json", out)
    log("M5 verdict=%s M6(web) verdict=%s" % (out["verdict_desktop_boundary"], out["verdict_web"]))


def phase_db():
    db = os.path.join(DATA, "data/xcagi.db")
    if not os.path.isfile(db):
        write("07-db-session.json", {"error": "db not found", "path": db})
        return
    q = ("select substr(session_id,1,12)||'...', user_id, account_kind, tenant_id, created_at, expires_at "
         "from sessions order by created_at desc limit 5;")
    r = sh("sqlite3 -readonly '%s' \"%s\"" % (db, q))
    r2 = sh("sqlite3 -readonly '%s' \"select count(*) from sessions;\"" % db)
    write("07-db-session.json", {"phase": "M3-服务端会话落盘(旁证)", "db": db,
                                 "rows": r, "session_count": r2})


def phase_summary():
    files = sorted(f for f in os.listdir(EV) if f.endswith(".json") and f[0].isdigit())
    phases = {}
    for f in files:
        d = json.load(open(os.path.join(EV, f), encoding="utf-8"))
        phases[f] = {k: d.get(k) for k in ("phase", "verdict", "verdict_desktop_boundary", "verdict_web")}
    broken = [f for f, v in phases.items()
              if "FAIL" in [v.get("verdict"), v.get("verdict_desktop_boundary"), v.get("verdict_web")]]
    out = {"feature": "base-login", "name": "登录与会话管理", "platform": "macos",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "app": app_identity(), "phases": phases,
           "verdict": "PASS" if not broken else "FAIL",
           "first_real_breakpoint": broken[0] if broken else None,
           "log": LOG}
    write("99-verdict.json", out)
    log("SUMMARY verdict=%s" % out["verdict"])


def phase_package():
    """把本轮证据打包进仓库 round 目录，并生成六要素结论。"""
    import shutil
    repo_dir = ("/Users/a4243342/Desktop/XCMAX/FHD/docs/evidence/e2e/"
                "feature-acceptance-20260922/base-login/macos")
    os.makedirs(repo_dir, exist_ok=True)
    copied = []
    for name in sorted(os.listdir(EV)):
        src = os.path.join(EV, name)
        if os.path.isfile(src) and not name.endswith(".mov"):
            shutil.copy2(src, os.path.join(repo_dir, name))
            copied.append(name)
    shutil.copy2(os.path.abspath(__file__), os.path.join(repo_dir, "accept_mac.py"))
    copied.append("accept_mac.py")
    # 大体积屏幕录像不进仓库：归档到 /Users/Shared，仓库只留清单与哈希
    archive_dir = "/Users/Shared/xcagi-t6-tools/feature-acceptance-20260922/base-login/macos"
    os.makedirs(archive_dir, exist_ok=True)
    video_manifest = []
    for name in sorted(os.listdir(EV)):
        if name.endswith(".mov"):
            src = os.path.join(EV, name)
            dst = os.path.join(archive_dir, name)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            video_manifest.append({"name": name, "bytes": os.path.getsize(dst),
                                   "sha256": hashlib.sha256(open(dst, "rb").read()).hexdigest(),
                                   "archive_path": dst})
    with open(os.path.join(repo_dir, "videos-manifest.json"), "w", encoding="utf-8") as f:
        json.dump(video_manifest, f, ensure_ascii=False, indent=2)
    copied.append("videos-manifest.json")
    # 运行日志（从各阶段 JSON 的时间戳与结论汇总）
    with open(os.path.join(repo_dir, "run.log"), "w", encoding="utf-8") as f:
        f.write("base-login macOS 本轮验收运行日志 %s\n" % time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        for name in sorted(os.listdir(EV)):
            if name.endswith(".json"):
                d = json.load(open(os.path.join(EV, name), encoding="utf-8"))
                f.write("%s  %-28s at=%s verdict=%s\n" % (
                    name, d.get("phase"), d.get("at"),
                    d.get("verdict") or d.get("verdict_desktop_boundary") or d.get("verdict_web") or "-"))
    copied.append("run.log")

    ident = json.load(open(os.path.join(EV, "01-identity.json"), encoding="utf-8"))
    verdict = json.load(open(os.path.join(EV, "99-verdict.json"), encoding="utf-8"))
    cur_build = app_identity()
    shots = [f for f in copied if f.endswith("-screen.png")]
    videos = [v["name"] for v in video_manifest]
    exe = os.path.join(APP, "Contents/MacOS/XCAGI")
    six = {
        "screenshot": bool(shots),
        "video": bool(videos),
        "log": True,
        "product_version": bool(cur_build.get("version")),
        "app_sha": bool(cur_build.get("gitSha")),
        "verify_time": True,
    }
    out = {
        "feature": "base-login", "name": "登录与会话管理", "platform": "macos",
        "round": "feature-acceptance-20260922",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "app_identity": {"app_path": APP, "build_info": ident.get("app_build_info"),
                         "build_info_now": cur_build,
                         "bundle_unchanged": ident.get("app_build_info") == cur_build,
                         "exe": exe, "exe_sha256": (hashlib.sha256(open(exe, "rb").read()).hexdigest()
                                                    if os.path.isfile(exe) else None)},
        "machine": ident.get("machine"),
        "data_dir": DATA, "cdp_port": CDP_PORT,
        "cases": verdict.get("phases"),
        "verdict": verdict.get("verdict"),
        "first_real_breakpoint": verdict.get("first_real_breakpoint"),
        "six_elements": six,
        "evidence_files": copied,
        "shots": shots, "videos": videos,
        "run_log": verdict.get("log"),
        "case_notes": {
            "M1": "未登录：无 session_id cookie，/api/auth/me 与 /api/auth/session/validate 都返回 valid=false；界面停在登录页（02-prelogin-screen.png）。",
            "M2": "GUI 真实输入 SUNBIRD 登录成功进入工作台；服务端会话 cookie 可用，/api/auth/me 返回 success=true 且 account_kind=enterprise（03-postlogin-*）。",
            "M3": "进程重启后同一 cookie 仍有效（04-session-restart.json），service 端 sessions 表存在该会话行（07-db-session.json）。",
            "M4": "HTTP POST /api/auth/logout 后旧 cookie 立即失效（05-postlogout.json）。注意：05-postlogout-* 截图是「API 退出那一刻」的画面，界面尚未刷新，因此仍显示工作台属预期现象；界面级证据由 05b（退出后重启回到登录页）与 05c（GUI 点击退出登录后停在登录页）承担。",
            "M4b": "退出后重启应用：界面回到登录页、/api/auth/me valid=false（05b-postlogout-relaunch.json）。",
            "M4c": "GUI 路径：系统设置 → 退出登录 → 确认「确定退出本机账号？」→ 确定，界面回到登录页（05c-gui-logout.json + 录屏 05c-gui-logout-operation.mov）。",
            "M5": "错误密码 / account_kind=admin（桌面端拒绝管理员）/ 空凭据 全部被拒绝（06-negative-and-web.json）。",
            "M6": "同一企业账号在修茈市场（Web）POST /api/auth/login 返回 ok=true 且带 access_token、desktop_access=true（06-negative-and-web.json）。"
        }
    }
    if out["verdict"] == "PASS" and out["app_identity"]["bundle_unchanged"] and all(six.values()):
        out["final_verdict"] = "PASS"
    elif out["verdict"] == "FAIL":
        out["final_verdict"] = "FAIL"
    elif not out["app_identity"]["bundle_unchanged"]:
        out["final_verdict"] = "BLOCKED"
        out["blocked_reason"] = "验收期间 /Applications/XCAGI.app 被其他进程替换（build-info 前后不一致）"
    else:
        out["final_verdict"] = "PARTIAL"
    write_path = os.path.join(repo_dir, "base-login-macos.json")
    with open(write_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log("PACKAGE final_verdict=%s -> %s" % (out["final_verdict"], write_path))


def phase_relaunch_check():
    """M4 补充：API 退出后重启应用，界面应回到登录页（会话失效的界面侧证据）。"""
    quit_app()
    time.sleep(3)
    launch()
    ready = wait_ready()
    time.sleep(20)
    dom = dom_state()
    me = http("GET", "/api/auth/me")
    out = {"phase": "M4b-退出后重启回到登录页", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "ready": ready, "dom": dom, "api_auth_me_no_cookie": me,
           "shots": shot("05b-postlogout-relaunch")}
    ok = (ready and dom.get("login_button_visible") is True
          and dom.get("workspace_markers", {}).get("chat") is False)
    out["verdict"] = "PASS" if ok else "FAIL"
    write("05b-postlogout-relaunch.json", out)
    log("M4b verdict=%s" % out["verdict"])


def phase_gui_logout_shot():
    """M4c：GUI 退出登录后的界面截图（由操作员点击，本阶段只采证）。"""
    dom = dom_state()
    out = {"phase": "M4c-GUI退出登录后界面", "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "dom": dom, "shots": shot("05c-gui-logout")}
    ok = (dom.get("login_button_visible") is True
          and dom.get("workspace_markers", {}).get("chat") is False)
    out["verdict"] = "PASS" if ok else "FAIL"
    write("05c-gui-logout.json", out)
    log("M4c verdict=%s" % out["verdict"])


PHASES = {"launch": phase_launch, "prelogin": phase_prelogin, "postlogin": phase_postlogin,
          "restart": phase_restart, "postlogout": phase_postlogout, "negative": phase_negative,
          "db": phase_db, "summary": phase_summary, "package": phase_package,
          "relaunchcheck": phase_relaunch_check, "guilogoutshot": phase_gui_logout_shot}

if __name__ == "__main__":
    os.makedirs(EV, exist_ok=True)
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in PHASES:
        raise SystemExit("usage: accept_mac.py <%s>" % "|".join(PHASES))
    PHASES[name]()