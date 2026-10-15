#!/usr/bin/env python3
"""G7 重测：登录 → 模板上传 → 列表 → 发货单生成出单（1.0.0.3 正式包实例）。

用法: python3 g7-retest-10003.py [--base http://127.0.0.1:17500] [--xlsx 模板.xlsx]
输出证据: FHD/docs/evidence/e2e/macos-release-1.0.0.3/g7-retest-10003.json
"""
import argparse, base64, hashlib, json, os, subprocess, sys, urllib.request, uuid

BASE = "http://127.0.0.1:17500"
USER = os.environ["XCAGI_TEST_USER"]  # 必填：本地验收租户账号（不入库）
PASS = os.environ["XCAGI_TEST_PASS"]  # 必填：本地验收租户口令（不入库）
EV_DIR = "/Users/Shared/XCMAX/FHD/docs/evidence/e2e/macos-release-1.0.0.3"
NO_PROXY = {"http": None, "https": None}

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
RESULT = {"phase": "G7-retest-10003", "steps": {}}


def call(method, path, data=None, headers=None, is_json=True):
    url = BASE + path
    h = dict(headers or {})
    body = None
    if data is not None:
        if is_json and not isinstance(data, (bytes, bytearray)):
            h["Content-Type"] = "application/json"
            body = json.dumps(data).encode()
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with opener.open(req, timeout=120) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jcall(method, path, data=None, headers=None):
    s, b = call(method, path, data, headers)
    try:
        return s, json.loads(b)
    except ValueError:
        return s, {"_raw": b[:500].decode("utf-8", "ignore")}


def step(name, fn):
    try:
        RESULT["steps"][name] = fn()
    except Exception as e:
        RESULT["steps"][name] = {"error": repr(e)}
    st = RESULT["steps"][name]
    print(f"== {name} ==>", json.dumps(st, ensure_ascii=False)[:300])
    return st


def make_xlsx(path):
    """生成最小发货单模板 xlsx（openpyxl 不可用时退化为手工 xlsx 结构）。"""
    try:
        from openpyxl import Workbook
    except ImportError:
        print("openpyxl missing; use existing template file"); return False
    wb = Workbook(); ws = wb.active; ws.title = "发货单"
    ws.append(["产品名称", "规格", "数量", "单价"])
    ws.append(["测试商品A", "500ml", 24, 3.5])
    ws.append(["测试商品B", "1L", 12, 7.0])
    wb.save(path); return True


def main():
    global BASE
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--xlsx", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "g7-template-probe.xlsx"))
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    os.makedirs(EV_DIR, exist_ok=True)

    if not os.path.exists(args.xlsx):
        make_xlsx(args.xlsx)
    assert os.path.exists(args.xlsx), "template xlsx unavailable"

    # warmup
    s, b = jcall("GET", "/api/health")
    RESULT["steps"]["health"] = {"status": s, "version": b.get("version")}

    # login
    s, b = jcall("POST", "/api/auth/login", {
        "username": USER, "password": PASS, "account_kind": "enterprise", "totp_code": ""})
    wt = b.get("web_tokens") or {} if isinstance(b, dict) else {}
    token = (wt.get("access_token") or b.get("access_token") or b.get("token") or "") if isinstance(b, dict) else ""
    sid = b.get("session_id", "") if isinstance(b, dict) else ""
    RESULT["steps"]["login"] = {"status": s, "success": bool(sid)}
    assert sid, f"login failed: {s} {b}"
    # upload 路由 get_logged_in_user 只认 session_id（cookie/X-Session-ID），
    # 且 POST 需 CSRF 双提交；先用 GET 换取 csrf_token cookie。
    csrf = ""
    resp = opener.open(urllib.request.Request(BASE + "/api/templates", headers={"Cookie": f"session_id={sid}"}))
    for v, val in resp.headers.items():
        if v.lower() == "set-cookie" and "csrf_token=" in val:
            csrf = val.split("csrf_token=")[1].split(";")[0]
    assert csrf, "no csrf cookie"
    COOKIE = f"session_id={sid}; csrf_token={csrf}"
    H = {"Cookie": COOKIE, "X-CSRF-Token": csrf}

    s, b = jcall("GET", "/api/auth/me", headers=H)
    RESULT["steps"]["auth_me"] = {"status": s, "user": b.get("user", {}).get("username") if isinstance(b, dict) and isinstance(b.get("user"), dict) else (b.get("username") if isinstance(b, dict) else None)}

    # upload（multipart）
    fname = os.path.basename(args.xlsx)
    boundary = uuid.uuid4().hex
    filebytes = open(args.xlsx, "rb").read()
    parts = []
    for k, v in [("template_name", "G7重测探针"), ("name", "G7重测探针"), ("template_scope", ""), ("type", "")]:
        parts += [f"--{boundary}", f'Content-Disposition: form-data; name="{k}"', "", v]
    parts += [f"--{boundary}", f'Content-Disposition: form-data; name="file"; filename="{fname}"',
              "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ""]
    body = ("\r\n".join(parts[:8] if False else []) )  # placeholder not used
    # 手工拼 multipart
    b_ = boundary.encode()
    buf = b""
    for k, v in [("template_name", "G7重测探针"), ("name", "G7重测探针"), ("template_scope", ""), ("type", "")]:
        buf += b"--" + b_ + b'\r\nContent-Disposition: form-data; name="' + k.encode() + b'"\r\n\r\n' + v.encode() + b"\r\n"
    buf += b"--" + b_ + b'\r\nContent-Disposition: form-data; name="file"; filename="' + fname.encode() + b'"\r\n'
    buf += b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    buf += filebytes + b"\r\n"
    buf += b"--" + b_ + b"--\r\n"
    s, b = call("POST", "/api/templates/upload", buf, {
        **H, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        ub = json.loads(b)
    except ValueError:
        ub = {"_raw": b[:300].decode("utf-8", "ignore")}
    template_id = (ub.get("template", {}) or {}).get("id") or ub.get("template_id") if isinstance(ub, dict) else None
    RESULT["steps"]["templates_upload"] = {"status": s, "template_id": template_id,
        "file_sha256": hashlib.sha256(filebytes).hexdigest()}
    assert 200 <= s < 300, f"upload failed: {s} {ub}"

    # templates list
    s, b = jcall("GET", "/api/templates", headers=H)
    names = json.dumps(b, ensure_ascii=False) if isinstance(b, list) else json.dumps(b, ensure_ascii=False)[:400]
    RESULT["steps"]["templates_list"] = {"status": s, "probe_present": "G7重测探针" in names}

    # 确保客户存在（shipment generate 要求客户已在 CRM）
    s, b = jcall("POST", "/api/customers", {
        "name": "G7重测客户(勿删)", "customer_name": "G7重测客户(勿删)", "contact": "", "phone": ""}, headers=H)
    RESULT["steps"]["customer_ensure"] = {"status": s, "customer_id": (b.get("data", {}) or {}).get("id") if isinstance(b, dict) else None}

    # shipment generate 出单
    s, b = jcall("POST", "/api/shipment/generate", {
        "unit_name": "G7重测客户(勿删)", "date": None,
        "products": [{"name": "测试商品A", "quantity": 24, "tin_spec": 25.0, "unit_price": 3.5, "amount": 84.0}],
    }, headers=H)
    RESULT["steps"]["shipment_generate"] = {"status": s, "success": b.get("success") if isinstance(b, dict) else None,
        "message": b.get("message") if isinstance(b, dict) else None,
        "doc_name": b.get("doc_name") or (b.get("data", {}) or {}).get("doc_name") if isinstance(b, dict) else None,
        "agent_status": b.get("agent_status") if isinstance(b, dict) else None,
        "run_id": b.get("run_id") if isinstance(b, dict) else None}
    print("\n==== G7 RESULT ====")
    print(json.dumps(RESULT, ensure_ascii=False, indent=2))
    out = os.path.join(EV_DIR, "g7-retest-10003.json")
    json.dump(RESULT, open(out, "w"), ensure_ascii=False, indent=2)
    print("evidence:", out)


if __name__ == "__main__":
    main()
