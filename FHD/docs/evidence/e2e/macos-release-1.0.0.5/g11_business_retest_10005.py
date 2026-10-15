#!/usr/bin/env python3
"""G11 业务链复测（1.0.0.5 升级后）：真实客户会话 → 模板上传 → 客户查重 → 发货单出单 → xlsx 下载回读。

与 1.0.0.4 的 g7_business_retest.py 的差别：不再依赖 XCAGI_TEST_USER/PASS，
改为复用应用内真实登录会话（CDP Network.getAllCookies 导出），
因此升级/重启后只要会话仍有效即可继续以「陌生客户视角」跑业务链。

用法: python3 g11_business_retest_10005.py [--cookies <json>] [--base http://127.0.0.1:17500]
输出证据: round-20260918-g11-business-10005.json
"""
import argparse, hashlib, json, os, sys, urllib.error, urllib.request, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SESS = "G11重测提交 %s" % uuid.uuid4().hex[:8]
RESULT = {"phase": "G11-business-10005", "session_tag": SESS, "steps": {}}
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, data=None, headers=None, is_json=True, timeout=180):
    h = dict(headers or {})
    body = None
    if data is not None:
        if is_json and not isinstance(data, (bytes, bytearray)):
            h["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        else:
            body = data
    req = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jcall(method, path, data=None, headers=None):
    s, b = call(method, path, data, headers)
    try:
        return s, json.loads(b)
    except ValueError:
        return s, {"_raw": b[:400].decode("utf-8", "ignore")}


def derive_csrf(sid, base):
    """GET /api/templates 换 csrf_token cookie（POST 需 CSRF 双提交）。"""
    r = opener.open(urllib.request.Request(base + "/api/templates",
                                           headers={"Cookie": f"session_id={sid}"}), timeout=60)
    for k, v in r.headers.items():
        if k.lower() == "set-cookie" and "csrf_token=" in v:
            return v.split("csrf_token=")[1].split(";")[0]
    return ""


def make_xlsx(path):
    try:
        from openpyxl import Workbook
    except ImportError:
        return False
    wb = Workbook(); ws = wb.active; ws.title = "发货单"
    ws.append(["产品名称", "规格", "数量", "单价"])
    ws.append(["G11验收商品A", "500ml", 24, 3.5])
    ws.append(["G11验收商品B", "1L", 12, 7.0])
    wb.save(path); return True


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:17500")
    ap.add_argument("--cookies", default=os.path.join(HERE, "round-20260918-g11-session-cookies.json"))
    ap.add_argument("--xlsx", default=os.path.join(HERE, "g11-template-probe-10005.xlsx"))
    ap.add_argument("--out", default=os.path.join(HERE, "round-20260918-g11-business-10005.json"))
    a = ap.parse_args()
    BASE = a.base.rstrip("/")
    ck = {c["name"]: c["value"] for c in json.load(open(a.cookies))}
    H = {"Cookie": f"session_id={ck['session_id']}; csrf_token={ck['csrf_token']}",
         "X-CSRF-Token": ck["csrf_token"]}

    s, b = jcall("GET", "/api/health")
    RESULT["steps"]["health"] = {"status": s, "version": b.get("version"),
        "git_sha": (b.get("build") or {}).get("git_sha", "")[:12], "runtime": (b.get("runtime") or {}).get("status")}

    s, b = jcall("GET", "/api/auth/me", headers=H)
    user = ((b.get("data") or {}).get("user") or {}) if isinstance(b, dict) else {}
    perms = ((b.get("data") or {}).get("permissions") or []) if isinstance(b, dict) else []
    RESULT["steps"]["session_reuse"] = {"status": s, "success": b.get("success"),
        "username": user.get("username"), "user_id": user.get("id"),
        "permission_count": len(perms), "has_shipment_edit": "shipment.edit" in perms}

    if not os.path.exists(a.xlsx):
        make_xlsx(a.xlsx)
    assert os.path.exists(a.xlsx), "template xlsx unavailable"

    fname = os.path.basename(a.xlsx)
    filebytes = open(a.xlsx, "rb").read()
    boundary = uuid.uuid4().hex
    b_ = boundary.encode()
    buf = b""
    for k, v in [("template_name", SESS), ("name", SESS), ("template_scope", ""), ("type", "")]:
        buf += b"--" + b_ + b'\r\nContent-Disposition: form-data; name="' + k.encode() + b'"\r\n\r\n' + v.encode() + b"\r\n"
    buf += b"--" + b_ + b'\r\nContent-Disposition: form-data; name="file"; filename="' + fname.encode() + b'"\r\n'
    buf += b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    buf += filebytes + b"\r\n--" + b_ + b"--\r\n"
    s, b = call("POST", "/api/templates/upload", buf, {**H, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        ub = json.loads(b)
    except ValueError:
        ub = {"_raw": b[:300].decode("utf-8", "ignore")}
    RESULT["steps"]["templates_upload"] = {"status": s, "template_id": (ub.get("template", {}) or {}).get("id"),
        "file_sha256": hashlib.sha256(filebytes).hexdigest()}

    s, b = jcall("GET", "/api/templates", headers=H)
    RESULT["steps"]["templates_list_probe_present"] = {"status": s,
        "probe_present": SESS in json.dumps(b, ensure_ascii=False)}

    s, b = jcall("POST", "/api/customers", {"name": "G11重测客户(勿删)", "customer_name": "G11重测客户(勿删)",
        "contact": "", "phone": ""}, headers=H)
    # 后端重复名返回 400，文案在 message（历史版本在 detail），两者都认。
    msg = ""
    if isinstance(b, dict):
        msg = str(b.get("message") or b.get("detail") or "")
    RESULT["steps"]["customer_retained"] = {"status": s, "already_exists": s == 400 and "已存在" in msg,
        "message": msg}

    s, b = jcall("POST", "/api/shipment/generate", {"unit_name": "G11重测客户(勿删)", "date": None,
        "products": [{"name": "G11验收商品A", "quantity": 24, "tin_spec": 25.0, "unit_price": 3.5, "amount": 84.0}]}, headers=H)
    doc_name = (b.get("doc_name") or (b.get("data", {}) or {}).get("doc_name")) if isinstance(b, dict) else None
    RESULT["steps"]["shipment_generate"] = {"status": s, "success": b.get("success") if isinstance(b, dict) else None,
        "message": b.get("message") if isinstance(b, dict) else None, "doc_name": doc_name}

    from urllib.parse import quote
    if doc_name:
        s2, raw = call("GET", f"/api/shipment/download/{quote(doc_name)}", headers=H)
        RESULT["steps"]["file_download"] = {"status": s2, "bytes": len(raw), "xlsx_magic": raw[:4] == b"PK\x03\x04",
            "sha256": hashlib.sha256(raw).hexdigest(), "filename": doc_name}
    else:
        RESULT["steps"]["file_download"] = {"skipped": True}

    ok = (RESULT["steps"]["session_reuse"].get("success") is True
          and RESULT["steps"]["templates_upload"]["status"] == 200
          and RESULT["steps"]["templates_list_probe_present"]["probe_present"] is True
          and RESULT["steps"]["customer_retained"].get("already_exists") is True
          and RESULT["steps"].get("shipment_generate", {}).get("status") == 200
          and RESULT["steps"].get("file_download", {}).get("xlsx_magic") is True)
    RESULT["verdict"] = "PASS" if ok else "BLOCKED"
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))
    json.dump(RESULT, open(a.out, "w"), ensure_ascii=False, indent=2)
    print("evidence:", a.out)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()