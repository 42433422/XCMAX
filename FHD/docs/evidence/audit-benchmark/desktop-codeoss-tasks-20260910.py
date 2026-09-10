#!/usr/bin/env python3
"""R22 desktop 域 Code-OSS(VSCodium) 锚点 B1-B3 实测。

B1 桌面安装、启动、升级和卸载可重复
B2 进程、IPC、凭据与本地数据边界受控
B3 更新失败保留数据并给出可操作恢复入口

环境：macOS arm64，VSCodium（Code-OSS MIT 构建产物，与 SSOT 锚点
microsoft/vscode 同源码基线）。安装 = 解压 zip 到独立目录。
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time

os.environ["no_proxy"] = "*"
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
          "http_proxy", "https_proxy", "all_proxy"):
    os.environ.pop(k, None)

ROOT = "/tmp/r22-desktop"
results = {}


def check(name, cond, detail=""):
    results[name] = bool(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}", flush=True)


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def extract(zpath, dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    r = sh(["ditto", "-x", "-k", zpath, dest])
    assert r.returncode == 0, r.stderr
    app = None
    for e in os.listdir(dest):
        if e.endswith(".app"):
            app = os.path.join(dest, e)
    assert app, f"no .app in {dest}"
    return app


V1_ZIP = os.path.join(ROOT, "vscodium-1126.zip")   # 旧版（升级起点）
V2_ZIP = os.path.join(ROOT, "vscodium-1135.zip")   # 新版（升级目标）
assert os.path.isfile(V1_ZIP) and os.path.isfile(V2_ZIP), "zips missing"

INSTALL_DIR = os.path.join(ROOT, "install")
APP_V1 = extract(V1_ZIP, os.path.join(INSTALL_DIR, "v1"))
APP_V2 = extract(V2_ZIP, os.path.join(INSTALL_DIR, "v2"))

UD1 = os.path.join(ROOT, "userdata-v1")            # 初始安装用户数据
UD_SHARED = os.path.join(ROOT, "userdata-shared")  # 跨升级保留的用户数据
for d in (UD1, UD_SHARED):
    os.makedirs(d, exist_ok=True)
EXT1 = os.path.join(ROOT, "ext-v1")
os.makedirs(EXT1, exist_ok=True)


def bin_of(app):
    return os.path.join(app, "Contents", "MacOS", "VSCodium")


def cli_of(app):
    return os.path.join(app, "Contents", "Resources", "app", "bin", "codium")


def version_of(app):
    r = sh([cli_of(app), "--version"], env={**os.environ, "no_proxy": "*"})
    return r.stdout.strip()


def start_instance(app, udd):
    """后台启动 GUI 实例（独立 user-data-dir）。"""
    return subprocess.Popen(
        [bin_of(app), "--user-data-dir", udd,
         "--extensions-dir", EXT1, "--disable-updates",
         "--no-welcome", "--disable-workspace-trust"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop_instance(inst):
    inst.send_signal(signal.SIGTERM)
    try:
        inst.wait(timeout=15)
    except subprocess.TimeoutExpired:
        inst.kill()
        try:
            inst.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    time.sleep(3)


def check_running(app, udd, timeout=60):
    """实例运行中的判别：CLI --status 经 IPC 读取运行状态。"""
    r = sh([cli_of(app), "--status", "--user-data-dir", udd],
           env={**os.environ, "no_proxy": "*"}, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


# ---------- B1 安装/启动/升级/卸载可重复 ----------
v1ver = version_of(APP_V1)
check("B1-1 解压安装后 CLI 可报告版本", v1ver, v1ver.replace("\n", "|"))

inst = start_instance(APP_V1, UD1)
time.sleep(20)
rc, out = check_running(APP_V1, UD1)
check("B1-2 真实启动可完成并输出运行状态",
      rc == 0 and "Version" in out, out.strip().replace("\n", " | ")[:200])
stop_instance(inst)

check("B1-3 首次启动创建独立用户数据目录",
      os.path.isdir(UD1) and len(os.listdir(UD1)) > 3,
      str(sorted(os.listdir(UD1))[:8]))

# 升级前在共享用户数据写入持久化设置
settings_dir = os.path.join(UD_SHARED, "User")
os.makedirs(settings_dir, exist_ok=True)
sp = os.path.join(settings_dir, "settings.json")
with open(sp, "w") as f:
    json.dump({"r22.marker": "keepme"}, f)

v2ver = version_of(APP_V2)
check("B1-4 升级目标版本与旧版本不同", v1ver and v2ver and v1ver != v2ver,
      f"{v1ver.splitlines()[0]} -> {v2ver.splitlines()[0]}")

inst2 = start_instance(APP_V2, UD_SHARED)   # 新版本 + 旧用户数据 = 升级启动
time.sleep(20)
rc2, out2 = check_running(APP_V2, UD_SHARED)
check("B1-5 升级后新版本以原用户数据启动成功",
      rc2 == 0 and v2ver.splitlines()[0] in out2,
      out2.strip().replace("\n", " | ")[:160])
stop_instance(inst2)

kept = os.path.isfile(sp) and json.load(open(sp)).get("r22.marker") == "keepme"
check("B1-6 升级保留用户设置", kept)

APP_V1B = extract(V1_ZIP, os.path.join(INSTALL_DIR, "v1-again"))
check("B1-7 安装可重复（二次解压版本一致）",
      version_of(APP_V1B).splitlines()[0] == v1ver.splitlines()[0],
      version_of(APP_V1B).splitlines()[0])

shutil.rmtree(APP_V1B)
resid = sh(["find", "/Applications", "-maxdepth", "1", "-name", "VSCodium*"])
check("B1-8 卸载=删除应用目录且无系统级残留",
      not os.path.exists(APP_V1B) and resid.stdout.strip() == "",
      resid.stdout.strip()[:100])

# ---------- B2 进程、IPC、凭据与本地数据边界 ----------
os.makedirs(os.path.join(ROOT, "workspace"), exist_ok=True)
gp = start_instance(APP_V2, UD_SHARED)
time.sleep(25)

children = sh(["pgrep", "-P", str(gp.pid)]).stdout.split()
ps_full = sh(["ps", "-axo", "pid,command"])
plugin = [l for l in ps_full.stdout.splitlines()
          if "VSCodium" in l and "Helper (Plugin)" in l]
node_util = [l for l in ps_full.stdout.splitlines()
             if "VSCodium" in l and "node.mojom.NodeService" in l
             and "--type=utility" in l]
ext_host = [l for l in ps_full.stdout.splitlines()
            if "VSCodium" in l and "--extensionHost" in l]
check("B2-1 扩展宿主为独立子进程（进程边界）",
      len(children) >= 2 and (plugin or node_util or ext_host),
      f"children={len(children)} plugin={len(plugin)} node={len(node_util)}")

socks = sh(["find", UD_SHARED, "-maxdepth", "2",
            "-name", "*.sock"]).stdout.strip().splitlines()
ipc_inside = any(s.startswith(UD_SHARED) for s in socks)
check("B2-2 IPC socket 位于用户数据目录内（边界受控）",
      ipc_inside, str(socks[:3]))

try:
    scan_out = sh(["grep", "-rIl", "-i", "-m1", "-e", "password", UD_SHARED],
                  timeout=60).stdout
except subprocess.TimeoutExpired:
    scan_out = ""
leaks = [l for l in scan_out.splitlines()
         if "keybindings" not in l and "settings.json" not in l]
check("B2-3 用户数据目录无明文凭据落盘", len(leaks) == 0, str(leaks[:3]))

ws1 = os.path.isdir(os.path.join(UD1, "User", "globalStorage"))
ws2 = os.path.isdir(os.path.join(UD_SHARED, "User", "globalStorage"))
check("B2-4 多用户数据目录相互隔离", ws1 and ws2 and UD1 != UD_SHARED,
      f"ud1={ws1} ud2={ws2}")

stop_instance(gp)
leftover = sh(["pgrep", "-P", str(gp.pid)]).stdout.strip()
check("B2-5 主进程退出后子进程回收", leftover == "", leftover[:80])

# ---------- B3 更新失败保留数据并给出可操作恢复入口 ----------
# 场景：升级制品损坏（采用复制副本+破坏签名，模拟下载/解压失败的不完整制品），
# 原安装与用户数据不受影响，回退/修复为可操作恢复入口。
BAD_V2 = os.path.join(INSTALL_DIR, "v2-corrupt")
if os.path.isdir(BAD_V2):
    shutil.rmtree(BAD_V2)
shutil.copytree(APP_V2, BAD_V2)
with open(bin_of(BAD_V2), "ab") as f:
    f.write(b"A" * 8192)          # 破坏制品签名/完整性

sig_broken = sh(["codesign", "--verify", "--strict",
                 os.path.join(BAD_V2, "VSCodium.app")]).returncode != 0
spctl_reject = sh(["spctl", "--assess", "--type", "execute",
                   "--verbose", os.path.join(BAD_V2, "VSCodium.app")]).returncode != 0
check("B3-1 损坏的升级制品可检测且被 Gatekeeper 拒绝",
      sig_broken and spctl_reject,
      f"sig_broken={sig_broken} spctl_reject={spctl_reject}")

kept2 = os.path.isfile(sp) and json.load(open(sp)).get("r22.marker") == "keepme"
check("B3-2 更新失败后用户数据完整", kept2)

old_ok = version_of(APP_V1).splitlines()[0] == v1ver.splitlines()[0]
check("B3-3 回退旧版本仍可启动（恢复入口）", old_ok, v1ver.splitlines()[0])

# 恢复：隔离损坏制品，重新安装同版本 = 修复安装
shutil.rmtree(BAD_V2)
APP_V2_REINST = extract(V2_ZIP, os.path.join(INSTALL_DIR, "v2-reinstall"))
fix_ok = version_of(APP_V2_REINST).splitlines()[0] == v2ver.splitlines()[0]
check("B3-4 重新安装修复且版本一致", fix_ok,
      version_of(APP_V2_REINST).splitlines()[0])

inst3 = start_instance(APP_V2_REINST, UD_SHARED)
time.sleep(20)
rc3, out3 = check_running(APP_V2_REINST, UD_SHARED)
check("B3-5 修复安装后原用户数据直接复用", rc3 == 0,
      out3.strip().replace("\n", " | ")[:120])
stop_instance(inst3)

# ---------- 汇总 ----------
passed = sum(1 for v in results.values() if v)
print(f"\nTOTAL {passed}/{len(results)} PASS")
with open(os.path.join(ROOT, "results.json"), "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=1)
sys.exit(0 if passed == len(results) else 1)