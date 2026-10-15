#!/usr/bin/env python3
"""G12 整机重启复验（1.0.0.5 / RELEASE_SHA=54325894c）。

前置：用户手动整机重启，并打开 /Applications/XCAGI.app（应用非开机自启动）。
本脚本只读校验冷启动后：内核 boottime 已变、安装身份未回退、健康、DB 完整性、
数据摘要未丢失、Mod 加载、会话仍有效，并复跑 G11 业务链。
输出：round-20260918-g12-post-reboot-verify-10005.json（verdict PASS/BLOCKED）。
"""
import json, os, shlex, subprocess, sqlite3, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SHA = "54325894cc6e3fc2becfcbc98697a099310d9420"
VER = "1.0.0.5"
ROOT = "/Users/a4243342/Library/Application Support/XCAGI"
BASE = "http://127.0.0.1:17500"
op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PRE = json.load(open(os.path.join(HERE, "round-20260918-g12-pre-reboot-state-10005.json")))


def sh(argv):
    """执行只读命令。参数经 shlex 拆分后以 argv 形式调用，不经 shell。"""
    return subprocess.run(shlex.split(argv), capture_output=True, text=True).stdout.strip()


def count_files(p):
    return sum(len(fs) for _, _, fs in os.walk(p)) if os.path.isdir(p) else 0


def digest():
    d = {}
    db = os.path.join(ROOT, "data", "xcagi.db")
    d["xcagi.db.bytes"] = os.path.getsize(db) if os.path.isfile(db) else -1
    vec = os.path.join(ROOT, "data", "excel_vectors.db")
    d["excel_vectors.db.bytes"] = os.path.getsize(vec) if os.path.isfile(vec) else -1
    d["mod_dbs.files"] = count_files(os.path.join(ROOT, "data", "mod_dbs"))
    for s in ("uploads", "mods", "models"):
        d[s + ".files"] = count_files(os.path.join(ROOT, s))
    bdir = os.path.join(ROOT, "backups")
    bks = sorted((f for f in os.listdir(bdir) if f.startswith("xcagi-") and f.endswith(".db")),
                 key=lambda f: os.path.getmtime(os.path.join(bdir, f))) if os.path.isdir(bdir) else []
    d["backups.files"] = len(bks)
    d["backups.latest"] = bks[-1] if bks else ""
    return d


def get(path, headers=None):
    try:
        r = op.open(urllib.request.Request(BASE + path, headers=headers or {}), timeout=60)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, "error: %s" % e


def main():
    out = {"schema": "xcagi.gate.evidence.v1", "gate": "G12", "platform": "macos",
           "round": "2026-09-18", "release_sha": SHA, "product_version": VER, "sku": "enterprise",
           "captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "steps": {}}

    boot_now = sh("sysctl -n kern.boottime")
    out["steps"]["kernel_boottime"] = {"before": PRE["boottime"], "after": boot_now,
                                       "changed": boot_now != PRE["boottime"]}

    out["steps"]["installed_identity"] = json.load(open("/Applications/XCAGI.app/Contents/Resources/build-info.json"))
    out["steps"]["app_owner"] = sh("ls -ld /Applications/XCAGI.app")
    out["steps"]["app_pid"] = sh("pgrep -f '/Applications/XCAGI.app/Contents/MacOS/XCAGI$'")
    out["steps"]["backend_pid"] = sh("pgrep -f 'xcagi-backend --desktop'")

    s, b = get("/api/health")
    try:
        hj = json.loads(b)
    except ValueError:
        hj = {}
    out["steps"]["health"] = {"status": s, "state": hj.get("status"), "version": hj.get("version"),
                              "git_sha": (hj.get("build") or {}).get("git_sha"),
                              "runtime": (hj.get("runtime") or {}).get("status"),
                              "blockers": (hj.get("runtime") or {}).get("blockers")}

    try:
        con = sqlite3.connect("file:%s?mode=ro" % os.path.join(ROOT, "data", "xcagi.db"), uri=True, timeout=60)
        out["steps"]["db_quick_check"] = con.execute("PRAGMA quick_check").fetchone()[0]
        con.close()
    except Exception as e:
        out["steps"]["db_quick_check"] = "error: %s" % e

    cur = digest()
    keys = ("xcagi.db.bytes", "excel_vectors.db.bytes", "mod_dbs.files", "uploads.files", "mods.files", "models.files")
    pre_d = PRE["digest"]
    out["steps"]["data_digest"] = {
        "before_reboot": pre_d, "after_reboot": cur,
        "lost": [f"{k}: {pre_d.get(k)} -> {cur.get(k)}" for k in keys if pre_d.get(k, 0) > 0 and cur.get(k, 0) < pre_d[k]],
        "gained": [f"{k}: {pre_d.get(k)} -> {cur.get(k)}" for k in keys if cur.get(k, 0) > pre_d.get(k, 0)],
    }

    s, b = get("/api/mods/loading-status")
    try:
        lj = json.loads(b).get("data", {})
    except ValueError:
        lj = {}
    out["steps"]["mods_loading"] = {"status": s, "mods_loaded": lj.get("mods_loaded"),
                                    "installed": len(lj.get("installed_mod_ids") or []),
                                    "load_mismatch": lj.get("load_mismatch"),
                                    "load_errors": lj.get("load_errors")}

    ck = {c["name"]: c["value"] for c in json.load(open(os.path.join(HERE, "round-20260918-g11-session-cookies.json")))}
    H = {"Cookie": f"session_id={ck['session_id']}; csrf_token={ck['csrf_token']}", "X-CSRF-Token": ck["csrf_token"]}
    s, b = get("/api/auth/me", H)
    try:
        mj = json.loads(b).get("data", {})
    except ValueError:
        mj = {}
    out["steps"]["session_after_reboot"] = {"status": s, "username": (mj.get("user") or {}).get("username"),
                                            "valid": s == 200 and bool((mj.get("user") or {}).get("username"))}

    # G11 业务链复跑（写入独立文件）
    rc = subprocess.run([sys.executable, os.path.join(HERE, "g11_business_retest_10005.py"),
                         "--out", os.path.join(HERE, "round-20260918-g11-business-post-reboot-10005.json"),
                         "--xlsx", os.path.join(HERE, "g11-template-probe-10005.xlsx")],
                        capture_output=True, text=True)
    out["steps"]["business_retest_exit"] = rc.returncode
    try:
        out["steps"]["business_retest"] = json.load(open(os.path.join(HERE, "round-20260918-g11-business-post-reboot-10005.json")))
    except Exception as e:
        out["steps"]["business_retest"] = {"error": str(e), "stderr": rc.stderr[-500:]}

    st = out["steps"]
    ok = (st["kernel_boottime"]["changed"] is True
          and st["installed_identity"].get("gitSha") == SHA
          and st["installed_identity"].get("version") == VER
          and st["health"].get("state") == "healthy" and st["health"].get("version") == VER
          and st["health"].get("git_sha") == SHA
          and st["db_quick_check"] == "ok"
          and not st["data_digest"]["lost"]
          and st["mods_loading"].get("mods_loaded") == 15 and st["mods_loading"].get("load_mismatch") is False
          and not (st["mods_loading"].get("load_errors") or [])
          and st["session_after_reboot"].get("valid") is True
          and st["business_retest_exit"] == 0)
    out["verdict"] = "PASS" if ok else "BLOCKED"
    p = os.path.join(HERE, "round-20260918-g12-post-reboot-verify-10005.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("evidence:", p)
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()