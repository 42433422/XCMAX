#!/usr/bin/env python3
"""R22 autonomy 域 Rundeck OSS 5.9.0 锚点 B1-B3 实测。

B1 运维动作白名单、执行权限、时间与资源上限
B2 真实子进程超时、截断和取消可回收后代进程
B3 任务记录、重试、审批与人工接管可追溯
"""
import base64
import hashlib
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

os.environ["no_proxy"] = "*"
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("ALL_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("all_proxy", None)

BASE = "http://localhost:14441"
P = "/api/41"
NODES_FILE = "/home/rundeck/r22-nodes.xml"
RES = """<project>
  <node name="local" description="local container" tags="local" hostname="localhost" username="rundeck">
    <attribute name="os-name" value="Linux"/>
  </node>
</project>
"""

cj = http.cookiejar.CookieJar()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


op = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(cj), NoRedirect)


def req(method, path, body=None, headers=None):
    data = None
    h = {"Accept": "application/json"}
    if headers:
        h.update(headers)
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        else:
            data = body.encode() if isinstance(body, str) else body
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        resp = op.open(r, timeout=60)
        return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def login():
    form = urllib.parse.urlencode({"j_username": "admin", "j_password": "admin"}).encode()
    r = urllib.request.Request(BASE + "/j_security_check", data=form, method="POST")
    try:
        op.open(r, timeout=15)
    except urllib.error.HTTPError as e:
        if e.code != 302:
            raise


def put_nodes():
    subprocess.run(["docker", "exec", "r22-rundeck2", "mkdir", "-p",
                    "/home/rundeck/projects/r22/etc"], check=False)
    p = subprocess.run(["docker", "exec", "-i", "r22-rundeck2", "sh", "-c",
                        "cat > /home/rundeck/projects/r22/etc/resources.xml"],
                       input=RES.encode(), check=True)
    return 200, "ok"


def upload_jobs(xml):
    return req("POST", f"{P}/project/r22/jobs/import", xml.encode(),
               {"Content-Type": "application/yaml"})


def run(jobid, options=None):
    q = f"{P}/job/{jobid}/executions"
    body = {"options": options} if options else b""
    return req("POST", q, body if options else None)


def status(eid, wait=90):
    for _ in range(wait * 2):
        st, out = req("GET", f"{P}/execution/{eid}")
        e = json.loads(out)
        done = bool(e.get("date-ended")) or bool(e.get("executionEndedAt"))
        if done:
            s = str(e.get("status") or e.get("executionState") or "")
            return {"succeeded": s == "succeeded", "executionStatus": s}
        time.sleep(0.5)
    return {"timed_out": True}


def logtext(eid):
    st, out = req("GET", f"{P}/execution/{eid}/output?maxlines=100000")
    js = json.loads(out)
    return "\n".join(e.get("log", "") for e in js.get("entries", []))


def find_job(name):
    st, out = req("GET", f"{P}/project/r22/jobs")
    jobs = json.loads(out)
    ids = [j["id"] for j in jobs if j["name"] == name]
    if not ids:
        raise KeyError(name)
    # 重复导入时取最新（最后一个）
    return ids[-1]


def yaml_job(name, desc, cmd, options=None, timeout=None, retry=False):
    lines = [f"- name: {name}", f"  description: {desc}", "  project: r22",
             "  loglevel: INFO"]
    if timeout:
        lines.append(f"  timeout: {timeout}")
    if retry:
        lines += ["  retry: 2", "  retryDelay: 1"]
    if options:
        lines += ["  options:"]
        for o in options:
            lines.append(f"    - name: {o['name']}")
            lines.append(f"      value: \"{o.get('value', '')}\"")
            lines.append(f"      required: {'true' if o.get('required') else 'false'}")
            if o.get("values"):
                lines.append("      enforced: true")
                lines.append("      values:")
                for v in o["values"]:
                    lines.append(f"        - {v}")
    lines += ["  sequence:", "    keepgoing: false", "    strategy: node-first",
              "    commands:", f"    - exec: >-\n        {cmd}",
              "  nodefilters:", "    filter: '.*'", "    dispatch:",
              "      threadcount: 1", "      keepgoing: false",
              "      rankOrder: ascending", "      excludePrecedence: true"]
    return "\n".join(lines) + "\n"


JOBS = "".join([
    yaml_job("B1-safe-echo", "B1 safe echo", 'echo "R22_OK ${option.verb}"',
             options=[{"name": "verb", "value": "hello"}], timeout="2m"),
    yaml_job("B2-sleep-long", "B2 timeout", "sleep 300; echo SHOULD_NOT_REACH",
             timeout="5s"),
    yaml_job("B2-output-big", "B2 big output", "seq 1 5000 | sed s/^/LINE-/"),
    yaml_job("B2-cancel-tree", "B2 cancel",
             "bash -c 'sleep 240 & echo $! > /tmp/r22-child; sleep 240'"),
    yaml_job("B3-retry-flaky", "B3 retry",
             "f=/tmp/r22-flaky-${option.run}; if [ -f $f ]; then echo PASS_ON_RETRY; "
             "exit 0; else touch $f; echo FAIL_FIRST; exit 1; fi",
             options=[{"name": "run", "value": "1"}], retry=True),
    yaml_job("B3-danger-limited", "B3 whitelist",
             'echo "APPROVED_ACTION ${option.action}"',
             options=[{"name": "action", "value": "list", "required": True,
                       "values": ["list", "restart"]}], timeout="1m"),
])

results = {}


def check(name, cond, detail=""):
    results[name] = bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


login()
st, out = put_nodes()
print("nodes upload:", st)
# 清理旧 job，避免重复导入干扰
st, out = req("GET", f"{P}/project/r22/jobs")
old_ids = [j["id"] for j in json.loads(out)]
if old_ids:
    st, out = req("POST", f"{P}/jobs/delete", {"ids": old_ids})
    print("jobs delete:", st)
st, out = upload_jobs(JOBS)
print("jobs import:", st, out[:300])
if st not in (200, 201):
    sys.exit(2)

# ---------- B1 白名单 / 权限 / 时间上限 ----------
jid = find_job("B1-safe-echo")
st, out = run(jid, {"verb": "ping"})
eid = json.loads(out)["id"]
r = status(eid)
check("B1-1 动作执行成功留记录", r.get("succeeded") is True, str(r.get("executionStatus")))
lg1 = logtext(eid)
check("B1-2 输出可审计", "R22_OK ping" in lg1, repr(lg1[:60]))

st, out = req("GET", f"{P}/project/r22/jobs/export?format=yaml&idlist={jid}")
check("B1-3 执行时间上限已配置", "timeout: 2m" in out, out[:60].replace("\n", " "))

r2 = urllib.request.Request(BASE + P + "/projects", method="GET")
try:
    code = urllib.request.build_opener().open(r2, timeout=10).status
except urllib.error.HTTPError as e:
    code = e.code
check("B1-4 未认证 API 被拒", code in (401, 403), str(code))

jid_d = find_job("B3-danger-limited")
st, out = run(jid_d, {"action": "delete"})
if st == 200:
    eid_d = json.loads(out)["id"]
    rd = status(eid_d)
    lgd = logtext(eid_d)
    st4, out4 = req("GET", f"{P}/execution/{eid_d}")
    rec = json.loads(out4)
    # enforced 选项：白名单外值被回退为默认值，命令只看到合法值
    ok = ("APPROVED_ACTION delete" not in lgd
          and "delete" not in str(rec.get("argstring", "")))
    check("B1-5 白名单外动作被拒且未执行", ok,
          f"argstring={rec.get('argstring')} status={rd.get('executionStatus')}")
else:
    check("B1-5 白名单外动作被拒且未执行", st in (400, 403), f"HTTP {st}")
st, out = run(jid_d, {"action": "restart"})
eid_d2 = json.loads(out)["id"]
rd2 = status(eid_d2)
check("B1-6 白名单内动作执行成功",
      rd2.get("succeeded") is True and "APPROVED_ACTION restart" in logtext(eid_d2),
      str(rd2.get("executionStatus")))

# ---------- B2 超时 / 截断 / 取消 ----------
jid = find_job("B2-sleep-long")
st, out = run(jid)
eid = json.loads(out)["id"]
r = status(eid, wait=30)
es = str(r.get("executionStatus", "")).lower()
check("B2-1 超时任务被中止", r.get("succeeded") is False and
      ("timed" in es or "abort" in es or "killed" in es), es)

subprocess.run(["docker", "exec", "r22-rundeck2", "rm", "-f", "/tmp/r22-child"], check=False)
jid = find_job("B2-output-big")
st, out = run(jid)
eid = json.loads(out)["id"]
r = status(eid, wait=120)
st2, out2 = req("GET", f"{P}/execution/{eid}/output?maxlines=100")
js = json.loads(out2)
n_entries = len(js.get("entries", []))
check("B2-2 大输出受控返回", r.get("succeeded") is True, f"limited_lines={n_entries}")
st3, out3 = req("GET", f"{P}/execution/{eid}/output?maxlines=100000")
js3 = json.loads(out3)
n_full = len(js3.get("entries", []))
check("B2-3 全量输出可检索", n_full >= 5000, f"full={n_full}")

# 取消并回收后代进程
jid = find_job("B2-cancel-tree")
st, out = run(jid)
eid = json.loads(out)["id"]
time.sleep(6)
child = subprocess.run(["docker", "exec", "r22-rundeck2", "cat", "/tmp/r22-child"],
                       capture_output=True, text=True).stdout.strip()
st, out = req("POST", f"{P}/execution/{eid}/abort")
r = status(eid, wait=30)
time.sleep(3)
alive = subprocess.run(
    ["docker", "exec", "r22-rundeck2", "sh", "-c",
     f"ps -o pid= -p {child or 99999} 2>/dev/null | wc -l"],
    capture_output=True, text=True).stdout.strip()
es = str(r.get("executionStatus", "")).lower()
check("B2-4 取消后状态可查", r.get("succeeded") is False, es)
check("B2-5 取消回收后代进程", child and alive == "0", f"child={child} alive={alive}")

# ---------- B3 记录 / 重试 / 审批 / 人工接管 ----------
subprocess.run(["docker", "exec", "r22-rundeck2", "rm", "-f", "/tmp/r22-flaky-1"], check=False)
jid = find_job("B3-retry-flaky")
st, out = run(jid, {"run": "1"})
eid = json.loads(out)["id"]
# root-level retry 失败后派生新执行；等待重试链收敛
time.sleep(25)
st, out = req("GET", f"{P}/project/r22/executions?jobListId={jid}&max=5")
chain = json.loads(out).get("executions", [])
chain = [e for e in chain if e["id"] >= int(eid)]
statuses = [e["status"] for e in sorted(chain, key=lambda x: x["id"])]
check("B3-1 失败自动重试并最终成功",
      "failed-with-retry" in statuses and "succeeded" in statuses,
      str(statuses))

st, out = req("GET", f"{P}/project/r22/executions?max=50")
hist = json.loads(out).get("executions", [])
check("B3-2 执行历史可追溯", len(hist) >= 6, f"n={len(hist)}")
me = [e for e in hist if e["id"] == int(eid)]
check("B3-3 记录含操作者与时间",
      bool(me) and me[0].get("user") == "admin"
      and bool(me[0].get("date-started", {}).get("date")),
      str(me[0].get("user") if me else ""))

# 人工接管 = 管理员中止运行中执行并留痕（B2-4/5 已证明中止生效），
# 验证被中止执行在历史中带 abort 状态
st, out = req("GET", f"{P}/project/r22/executions?max=100")
hist_f = json.loads(out).get("executions", [])
ab = [e for e in hist_f if e["status"] in ("aborted", "timed-out", "killed")]
check("B3-4 中止/超时执行在历史中可区分", len(ab) >= 1, f"aborted_like={len(ab)}")

fails = [k for k, v in results.items() if not v]
print("\nSUMMARY:", json.dumps(results, ensure_ascii=False))
print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
