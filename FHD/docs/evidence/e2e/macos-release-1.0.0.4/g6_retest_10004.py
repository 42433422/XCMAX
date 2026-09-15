"""G6 复测：1.0.0.4 OTA 后 Mod/AI 员工加载（对齐 1.0.0.3 g6 证据结构）。
用法: XCAGI_TEST_USER=... XCAGI_TEST_PASS=... python3 g6_retest_10004.py
输出: g6-post-ota-10004.json
"""
import json, os, urllib.request

BASE = "http://127.0.0.1:17500"
USER, PASS = os.environ["XCAGI_TEST_USER"], os.environ["XCAGI_TEST_PASS"]
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def call(method, path, token=None, payload=None):
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with opener.open(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode())

R = {"phase": "G6-Mod/AI员工加载（1.0.0.4 OTA 后登录态）", "date": __import__("datetime").datetime.now().isoformat(timespec="seconds")}

s, login = call("POST", "/api/auth/login", payload={"username": USER, "password": PASS})
wt = login.get("web_tokens") or {} if isinstance(login, dict) else {}
tok = (wt.get("access_token") or login.get("access_token") or login.get("token") or "") if isinstance(login, dict) else ""
R["login"] = {"status": s, "success": bool(tok), "user": USER}

s, h = call("GET", "/api/health", token=tok)
R["health"] = {"status": s, "version": h.get("version")}

s, mods = call("GET", "/api/mods", token=tok)
mlist = mods if isinstance(mods, list) else (mods.get("mods") or mods.get("data") or [])
R["mods"] = {"status": s, "count": len(mlist)}
att = [m for m in mlist if isinstance(m, dict) and m.get("id") == "attendance-industry"]
R["mods"]["attendance_industry"] = ({"id": att[0].get("id"), "version": att[0].get("version"), "primary": att[0].get("primary", True)} if att else None)

try:
    s, emp = call("GET", "/api/employees", token=tok)
    catalog = ((emp.get("data") or {}).get("catalog") or {}) if isinstance(emp, dict) else {}
    split = catalog.get("split_mod_entries") or []
    R["employees"] = {"status": s, "catalog_schema": catalog.get("schema_version"),
                      "split_mod_entries": len(split),
                      "legacy_employee_ids": catalog.get("legacy_monolith_employee_ids"),
                      "split_ids": [e.get("employee_id") for e in split if isinstance(e, dict)][:8]}
except Exception as ex:
    R["employees"] = {"error": str(ex)}

try:
    s, ls = call("GET", "/api/mods/loading-status", token=tok)
    R["loading_status"] = {"status": s, "summary": ls if isinstance(ls, dict) and len(json.dumps(ls)) < 400 else "ok"}
except Exception as ex:
    R["loading_status"] = {"error": str(ex)}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "g6-post-ota-10004.json")
json.dump(R, open(out, "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
