#!/usr/bin/env python3
"""鸿蒙发版员 · AGC Publishing API 客户端(HarmonyOS .app 上传 + 提交审核)。

已验证的现代鸿蒙发布流(2026-06):
  1) client_id+secret 换 token (connect-api/api/oauth2/v1/token)
  2) GET upload-url/for-obs → 拿 OBS 预签名 PUT 地址 + objectId
  3) PUT .app 到 OBS
  4) PUT app-file-info 绑定 objectId 到版本
  5) POST app-submit 提交审核(--no-submit 可跳过)

密钥来自仓库外:~/XCMAX-runtime/harmony/signing/agc-api.env
  AGC_CLIENT_ID / AGC_CLIENT_SECRET / AGC_APP_ID
用法:publish-agc-harmony.py --app <signed.app> [--no-submit]
"""
import argparse, json, os, sys, urllib.request, urllib.parse, urllib.error

CONNECT = "https://connect-api.cloud.huawei.com"
ENV = os.path.expanduser("~/XCMAX-runtime/harmony/signing/agc-api.env")


def load_env():
    e = {}
    if os.path.exists(ENV):
        for ln in open(ENV):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                e[k] = v
    return e


def http(method, url, headers=None, data=None, json_resp=True):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=180)
        body = r.read().decode(errors="replace")
        return r.status, (json.loads(body) if json_resp and body else body)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def die(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--no-submit", action="store_true")
    a = ap.parse_args()

    env = load_env()
    cid = env.get("AGC_CLIENT_ID") or os.environ.get("AGC_CLIENT_ID")
    sec = env.get("AGC_CLIENT_SECRET") or os.environ.get("AGC_CLIENT_SECRET")
    appid = env.get("AGC_APP_ID") or os.environ.get("AGC_APP_ID")
    if not (cid and sec and appid):
        die(f"缺 AGC_CLIENT_ID/SECRET/APP_ID(放 {ENV})")
    if not os.path.isfile(a.app):
        die(f"找不到上架包: {a.app}")

    fn = os.path.basename(a.app)
    size = os.path.getsize(a.app)

    print("=== 1/5 取 token ===")
    s, t = http("POST", f"{CONNECT}/api/oauth2/v1/token", {"Content-Type": "application/json"},
                json.dumps({"grant_type": "client_credentials", "client_id": cid, "client_secret": sec}).encode())
    if not (isinstance(t, dict) and t.get("access_token")):
        die(f"取 token 失败: {t}")
    A = {"Authorization": f"Bearer {t['access_token']}", "client_id": cid, "Content-Type": "application/json"}

    print(f"=== 2/5 取 OBS 上传地址({fn}, {size}B)===")
    s, u = http("GET", f"{CONNECT}/api/publish/v2/upload-url/for-obs"
                f"?appId={appid}&fileName={urllib.parse.quote(fn)}&contentLength={size}&releaseType=1", A)
    if not (isinstance(u, dict) and u.get("ret", {}).get("code") == 0):
        die(f"取上传地址失败: {u}")
    info = u["urlInfo"]
    obj = info["objectId"]

    print("=== 3/5 PUT 上传到 OBS ===")
    ph = dict(info["headers"])
    ph["Content-Length"] = str(size)
    with open(a.app, "rb") as f:
        s, b = http(info.get("method", "PUT"), info["url"], ph, f.read(), json_resp=False)
    if s != 200:
        die(f"OBS 上传失败 HTTP {s}: {b}")

    print("=== 4/5 绑定文件到版本 ===")
    body = {"fileType": 5, "files": [{"fileName": fn, "fileDestUrl": obj}]}
    s, b = http("PUT", f"{CONNECT}/api/publish/v2/app-file-info?appId={appid}&releaseType=1", A,
                json.dumps(body).encode())
    if not (isinstance(b, dict) and b.get("ret", {}).get("code") == 0):
        die(f"绑定失败: {b}")
    print("   pkgVersion:", b.get("pkgVersion"))

    if a.no_submit:
        print("=== 5/5 跳过提交(--no-submit)。包已上传并挂到版本,可在 AGC 网页提交。 ===")
        return
    print("=== 5/5 提交审核 ===")
    s, b = http("POST", f"{CONNECT}/api/publish/v2/app-submit?appId={appid}&releaseType=1", A, b"")
    if not (isinstance(b, dict) and b.get("ret", {}).get("code") == 0):
        die(f"提交失败(常因应用信息/隐私政策未填齐): {b}")
    print(f"✅ 已提交华为审核(appId={appid})。审核 1-3 工作日。")


if __name__ == "__main__":
    main()
