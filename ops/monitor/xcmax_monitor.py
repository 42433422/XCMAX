#!/usr/bin/env python3
"""XCMAX 生产哨兵：每 5 分钟体检一次，异常状态迁移时告警（stdlib-only, py3.6+）。

检查项（对应历史真实事故）：
  - systemd 单元存活（fhd-full / modstore / modstore-scheduler / nginx）
  - HTTP 健康端点（FHD:5100 /api/health、MODstore:9999、调度器:9990）
  - 调度器 job 账本 /api/scheduler/runtime 的 stale/failing（根治「停摆 12 天没人知道」）
  - journal 错误爆发（根治「日崩 2516 次靠手动 SSH 发现」）
  - LLM 配额熄火信号（employee_evolution_circuit_break / 配额不足 爆发）
  - 磁盘 / 内存水位
  - 备份新鲜度（< 26h，根治「没有任何备份」的静默腐烂）
  - FHD 发布链健康（manifest 与已部署 sha 长期不一致 = auto-update 断了）
  - TLS 证书到期

告警去抖：状态机存于 /var/lib/xcmax-ops/state/monitor_state.json，
仅在 好→坏（立即）、坏→好（恢复通知）、坏持续超过 OPS_REALERT_HOURS（默认 24h）时发送。

用法：xcmax_monitor.py [--no-alert] [--json]
cron 由 ops/install.sh 安装（*/5 分钟，flock 防重入）。
"""

from __future__ import print_function

import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import notify  # noqa: E402

STATE_DIR = os.environ.get("OPS_STATE_DIR", "/var/lib/xcmax-ops")
STATE_FILE = os.path.join(STATE_DIR, "state", "monitor_state.json")
REALERT_HOURS = float(os.environ.get("OPS_REALERT_HOURS", "24"))

FHD_PORT = os.environ.get("OPS_FHD_PORT", "5100")
MODSTORE_PORT = os.environ.get("OPS_MODSTORE_PORT", "9999")
SCHEDULER_PORT = os.environ.get("OPS_SCHEDULER_PORT", "9990")
PAYMENT_PORT = os.environ.get("OPS_PAYMENT_PORT", "8080")
PAYMENT_ENABLED = os.environ.get("OPS_PAYMENT_ENABLED", "1") == "1"
UNITS = [
    u.strip()
    for u in os.environ.get(
        "OPS_UNITS", "fhd-full,modstore,modstore-scheduler,nginx"
    ).split(",")
    if u.strip()
]
BACKUP_DIR = os.environ.get("OPS_BACKUP_DIR", "/var/backups/xcmax")
MANIFEST = os.environ.get(
    "OPS_MANIFEST", "/var/www/update/releases/stable/server/fhd-manifest.json"
)
FHD_DEPLOY_ROOT = os.environ.get("OPS_FHD_DEPLOY_ROOT", "/opt/fhd-full")
TLS_DOMAIN = os.environ.get("OPS_DOMAIN", "xiu-ci.com")

JOURNAL_ERR_WARN = int(os.environ.get("OPS_JOURNAL_ERR_WARN", "30"))
JOURNAL_ERR_CRIT = int(os.environ.get("OPS_JOURNAL_ERR_CRIT", "200"))
QUOTA_BURST_WARN = int(os.environ.get("OPS_QUOTA_BURST_WARN", "5"))
DISK_WARN = int(os.environ.get("OPS_DISK_WARN", "88"))
DISK_CRIT = int(os.environ.get("OPS_DISK_CRIT", "95"))


def _run(cmd, timeout=15):
    """跑外部命令，返回 (rc, stdout)。命令缺失/超时不抛。"""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _http_get(url, timeout=8):
    """GET url，返回 (status_code_or_0, body_str)。0 = 连接失败/超时。"""
    import urllib.error
    import urllib.request

    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return resp.getcode(), resp.read(65536).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(65536).decode("utf-8", "replace")
        except Exception:
            body = ""
        return exc.code, body
    except Exception as exc:
        return 0, str(exc)


def _result(check_id, ok, level, detail):
    return {"id": check_id, "ok": bool(ok), "level": level, "detail": detail[:500]}


# ---------------------------------------------------------------- checks


def check_systemd_units():
    results = []
    for unit in UNITS:
        rc, out = _run(["systemctl", "is-active", unit], timeout=10)
        state = out.strip().splitlines()[0] if out.strip() else "unknown"
        results.append(
            _result(
                "svc:%s" % unit,
                rc == 0 and state == "active",
                "crit",
                "systemd %s" % state,
            )
        )
    return results


def check_http_endpoints():
    results = []

    code, _ = _http_get("http://127.0.0.1:%s/api/health" % FHD_PORT)
    if code != 200:
        # 生产旧构建可能没有 /api/health，回退 k8s 风格 liveness
        code2, _ = _http_get("http://127.0.0.1:%s/health/liveness" % FHD_PORT)
        ok = code2 == 200
        detail = "/api/health=%s /health/liveness=%s" % (code, code2)
    else:
        ok = True
        detail = "/api/health=200"
    results.append(_result("http:fhd", ok, "crit", detail))

    code, body = _http_get("http://127.0.0.1:%s/api/health" % MODSTORE_PORT)
    ok = code == 200
    if ok:
        try:
            ok = json.loads(body).get("ok", True) is not False
        except ValueError:
            pass
    results.append(_result("http:modstore", ok, "crit", "http=%s" % code))

    code, body = _http_get("http://127.0.0.1:%s/api/health" % SCHEDULER_PORT)
    ok = code == 200
    detail = "http=%s" % code
    if ok:
        try:
            doc = json.loads(body)
            if doc.get("ok") is False or doc.get("scheduler_running") is False:
                ok = False
                detail = "http=200 但 ok=%s scheduler_running=%s" % (
                    doc.get("ok"),
                    doc.get("scheduler_running"),
                )
        except ValueError:
            pass
    results.append(_result("http:scheduler", ok, "crit", detail))

    if PAYMENT_ENABLED:
        code, _ = _http_get("http://127.0.0.1:%s/actuator/health" % PAYMENT_PORT)
        results.append(
            _result("http:payment", code == 200, "warn", "actuator=%s" % code)
        )
    return results


def check_scheduler_runtime():
    """job_run 账本停摆检测——12 天停摆事故的自动化版。"""
    code, body = _http_get(
        "http://127.0.0.1:%s/api/scheduler/runtime" % SCHEDULER_PORT, timeout=15
    )
    if code != 200:
        return [
            _result(
                "sched:runtime", False, "warn", "runtime 端点 http=%s（无法判定停摆）" % code
            )
        ]
    try:
        doc = json.loads(body)
    except ValueError:
        return [_result("sched:runtime", False, "warn", "runtime 返回非 JSON")]
    stale = [j for j in doc.get("jobs", []) if j.get("state") == "stale"]
    failing = [j for j in doc.get("jobs", []) if j.get("state") == "failing"]
    if not stale and not failing:
        summary = doc.get("summary", {})
        return [
            _result(
                "sched:runtime",
                True,
                "warn",
                "%s 个 job 全部健康" % summary.get("total", "?"),
            )
        ]
    parts = []
    if stale:
        parts.append(
            "停摆(>26h 无成功): %s" % ", ".join(j.get("job_id", "?") for j in stale[:8])
        )
    if failing:
        parts.append(
            "连续失败: %s"
            % ", ".join(
                "%s(x%s)" % (j.get("job_id", "?"), j.get("consecutive_failures", "?"))
                for j in failing[:8]
            )
        )
    return [_result("sched:runtime", False, "warn", "; ".join(parts))]


def check_journal_errors():
    results = []
    rc, out = _run(
        [
            "journalctl",
            "-u", "fhd-full", "-u", "modstore", "-u", "modstore-scheduler",
            "--since", "10 min ago",
            "--no-pager", "-o", "cat",
        ],
        timeout=25,
    )
    if rc == 127:
        return [_result("journal:errors", True, "warn", "journalctl 不可用，跳过")]
    err_count = 0
    quota_count = 0
    quota_re = re.compile(
        r"配额不足|insufficient_quota|quota_exhausted|employee_evolution_circuit_break"
    )
    err_re = re.compile(r"Traceback|CRITICAL|\bERROR\b")
    for line in out.splitlines():
        if err_re.search(line):
            err_count += 1
        if quota_re.search(line):
            quota_count += 1
    level = "crit" if err_count >= JOURNAL_ERR_CRIT else "warn"
    results.append(
        _result(
            "journal:errors",
            err_count < JOURNAL_ERR_WARN,
            level,
            "近 10 分钟错误行 %s（warn>=%s crit>=%s）——按 2516 次/日事故标定"
            % (err_count, JOURNAL_ERR_WARN, JOURNAL_ERR_CRIT),
        )
    )
    results.append(
        _result(
            "journal:quota",
            quota_count < QUOTA_BURST_WARN,
            "warn",
            "近 10 分钟配额失败/熔断信号 %s 条——LLM 配额疑似熄火，loop 在空转" % quota_count,
        )
    )
    return results


def check_disk_mem():
    results = []
    try:
        st = os.statvfs("/")
        used_pct = 100 - (st.f_bavail * 100 // st.f_blocks)
        level = "crit" if used_pct >= DISK_CRIT else "warn"
        results.append(
            _result(
                "disk:root",
                used_pct < DISK_WARN,
                level,
                "根分区使用 %s%%" % used_pct,
            )
        )
    except OSError as exc:
        results.append(_result("disk:root", False, "warn", "statvfs 失败: %s" % exc))
    try:
        meminfo = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                meminfo[key.strip()] = int(rest.strip().split()[0])
        avail = meminfo.get("MemAvailable", 0)
        total = meminfo.get("MemTotal", 1)
        pct = avail * 100 // total
        results.append(
            _result("mem:avail", pct >= 5, "warn", "可用内存 %s%%" % pct)
        )
    except (IOError, OSError, ValueError, IndexError):
        results.append(_result("mem:avail", True, "warn", "/proc/meminfo 不可读，跳过"))
    return results


def check_backup_freshness():
    daily = os.path.join(BACKUP_DIR, "daily")
    newest = 0.0
    if os.path.isdir(daily):
        for name in os.listdir(daily):
            path = os.path.join(daily, name)
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                pass
    if not newest:
        return [
            _result(
                "backup:fresh", False, "crit", "无任何备份产物（%s/daily 为空）" % BACKUP_DIR
            )
        ]
    age_h = (time.time() - newest) / 3600.0
    return [
        _result(
            "backup:fresh",
            age_h < 26,
            "crit",
            "最新备份 %.1f 小时前" % age_h,
        )
    ]


def check_deploy_chain():
    """发布链健康：manifest（CI 推）与 .deploy-sha256（auto-update 消费）应收敛。"""
    if not os.path.exists(MANIFEST):
        return [
            _result(
                "deploy:chain",
                False,
                "warn",
                "manifest 不存在 %s——CI cvm-push-release 从未送达本机" % MANIFEST,
            )
        ]
    try:
        with open(MANIFEST, encoding="utf-8") as fh:
            doc = json.load(fh)
        manifest_sha = doc.get("sha256", "")
    except (ValueError, IOError, OSError) as exc:
        return [_result("deploy:chain", False, "warn", "manifest 解析失败: %s" % exc)]
    deployed_file = os.path.join(FHD_DEPLOY_ROOT, ".deploy-sha256")
    if not os.path.exists(deployed_file):
        return [
            _result(
                "deploy:chain",
                False,
                "warn",
                "%s 缺 .deploy-sha256——fhd-auto-update 从未在本机成功跑过（仍在手工 scp?）"
                % FHD_DEPLOY_ROOT,
            )
        ]
    try:
        with open(deployed_file, encoding="utf-8") as fh:
            deployed_sha = fh.read().strip()
    except (IOError, OSError):
        deployed_sha = ""
    manifest_age_h = (time.time() - os.path.getmtime(MANIFEST)) / 3600.0
    if manifest_sha and deployed_sha != manifest_sha and manifest_age_h > 6:
        return [
            _result(
                "deploy:chain",
                False,
                "warn",
                "manifest sha=%s… 已发布 %.1fh 但部署 sha=%s…（auto-update cron 断了?）"
                % (manifest_sha[:12], manifest_age_h, (deployed_sha or "无")[:12]),
            )
        ]
    return [
        _result(
            "deploy:chain", True, "warn", "已部署 sha=%s…" % (deployed_sha or "?")[:12]
        )
    ]


def check_tls_expiry():
    if not TLS_DOMAIN:
        return []
    try:
        ctx = ssl.create_default_context()
        try:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        except AttributeError:  # py3.6
            ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        with socket.create_connection((TLS_DOMAIN, 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=TLS_DOMAIN) as tls:
                cert = tls.getpeercert()
        not_after = cert.get("notAfter", "")
        expire_ts = ssl.cert_time_to_seconds(not_after)
        days = (expire_ts - time.time()) / 86400.0
        level = "crit" if days < 3 else "warn"
        return [
            _result(
                "cert:tls",
                days >= 14,
                level,
                "%s 证书 %.0f 天后到期" % (TLS_DOMAIN, days),
            )
        ]
    except Exception as exc:
        return [
            _result("cert:tls", False, "warn", "TLS 检查失败(%s): %s" % (TLS_DOMAIN, exc))
        ]


CHECKS = (
    check_systemd_units,
    check_http_endpoints,
    check_scheduler_runtime,
    check_journal_errors,
    check_disk_mem,
    check_backup_freshness,
    check_deploy_chain,
    check_tls_expiry,
)


# ---------------------------------------------------------- state machine


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (IOError, OSError, ValueError):
        return {}


def save_state(state):
    parent = os.path.dirname(STATE_FILE)
    if not os.path.isdir(parent):
        os.makedirs(parent)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def run_checks():
    results = []
    for fn in CHECKS:
        try:
            results.extend(fn())
        except Exception as exc:  # 单项检查崩溃不拖垮整轮
            results.append(
                _result("check:%s" % fn.__name__, False, "warn", "检查器异常: %s" % exc)
            )
    return results


def evaluate(results, state, now=None):
    """状态迁移 → (new_state, newly_bad, still_bad_realert, recovered)。"""
    now = now or time.time()
    newly_bad, realert, recovered = [], [], []
    new_state = {}
    for res in results:
        prev = state.get(res["id"], {})
        entry = {
            "status": "ok" if res["ok"] else "bad",
            "level": res["level"],
            "detail": res["detail"],
            "since": prev.get("since", now),
            "last_alert": prev.get("last_alert", 0),
        }
        if res["ok"]:
            if prev.get("status") == "bad":
                recovered.append(res)
                entry["since"] = now
            entry["last_alert"] = 0
        else:
            if prev.get("status") != "bad":
                entry["since"] = now
                entry["last_alert"] = now
                newly_bad.append(res)
            elif now - prev.get("last_alert", 0) >= REALERT_HOURS * 3600:
                entry["last_alert"] = now
                res = dict(res)
                res["detail"] += "（持续 %.1fh 未恢复）" % ((now - entry["since"]) / 3600)
                realert.append(res)
            else:
                entry["last_alert"] = prev.get("last_alert", now)
        new_state[res["id"]] = entry
    return new_state, newly_bad, realert, recovered


def format_report(results, newly_bad, realert, recovered):
    lines = []
    bad_now = newly_bad + realert
    if bad_now:
        lines.append("故障 (%d):" % len(bad_now))
        for res in sorted(bad_now, key=lambda r: (r["level"] != "crit", r["id"])):
            lines.append("  [%s] %s — %s" % (res["level"].upper(), res["id"], res["detail"]))
    if recovered:
        lines.append("恢复 (%d):" % len(recovered))
        for res in recovered:
            lines.append("  [OK] %s — %s" % (res["id"], res["detail"]))
    total_bad = sum(1 for r in results if not r["ok"])
    lines.append("")
    lines.append("全局: %d 异常 / %d 项检查" % (total_bad, len(results)))
    if total_bad:
        lines.append("当前所有异常项:")
        for res in results:
            if not res["ok"]:
                lines.append("  [%s] %s — %s" % (res["level"].upper(), res["id"], res["detail"]))
    lines.append("")
    lines.append("处置手册: /root/XCMAX/ops/README.md")
    return "\n".join(lines)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    no_alert = "--no-alert" in argv
    as_json = "--json" in argv

    results = run_checks()

    if as_json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    else:
        for res in results:
            print(
                "%-18s %-4s %s"
                % (res["id"], "OK" if res["ok"] else res["level"].upper(), res["detail"])
            )

    if no_alert:
        # 纯观察模式（安装自检用）：不落状态机、不告警，
        # 否则首次真 cron 会把既有故障误判为「已告警过」而静默。
        return 0

    state = load_state()
    new_state, newly_bad, realert, recovered = evaluate(results, state)
    save_state(new_state)

    to_alert = newly_bad + realert
    if to_alert:
        worst = "crit" if any(r["level"] == "crit" for r in to_alert) else "warn"
        crit_n = sum(1 for r in to_alert if r["level"] == "crit")
        title = "%d 项故障（%d crit）" % (len(to_alert), crit_n)
        notify.deliver(worst, title, format_report(results, newly_bad, realert, recovered))
    elif recovered:
        notify.deliver(
            "ok",
            "%d 项已恢复" % len(recovered),
            format_report(results, [], [], recovered),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
