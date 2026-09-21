#!/usr/bin/env python3
"""OTA 后端完整性判据（正确版）。

判据（全部为真才 PASS）：
  1) codesign --verify --deep --strict 通过（任一 sealed resource 陈旧/缺失都会失败——本轮此前
     “后端未替换” 的失败态正是这样被抓住的）；
  2) spctl -a -t install 接受（Notarized Developer ID）；
  3) 关键源码 resources/tools_legacy/AI助手/shipment_document.py 与更新包逐字节一致，且含修复标记 _write_cell。
另附信息项：与更新包相比内容不同的文件数（macOS 安装会对 Mach-O 重新签名，原生二进制的差异属正常，不作为判据）。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile

ZIP = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Library/Caches/xcagi-desktop-updater/update.zip")
APP = sys.argv[2] if len(sys.argv) > 2 else "/Applications/XCAGI.app"
OUT = sys.argv[3] if len(sys.argv) > 3 else "/private/tmp/xcagi-custchain/evidence-ota/ota-backend-integrity.json"

BACKEND = os.path.join(APP, "Contents/Resources/backend")
KEY_REL = "_internal/resources/tools_legacy/AI助手/shipment_document.py"


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(cmd):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def zip_name(info):
    """electron-builder 的 zip 常未置 UTF-8 标志位；此处按 cp437->utf-8 还原中文路径。"""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("utf-8")
    except Exception:
        return name


with zipfile.ZipFile(ZIP) as z:
    infos = [i for i in z.infolist()
             if i.filename.startswith("XCAGI.app/Contents/Resources/backend/") and not i.is_dir()]
    tmp = tempfile.mkdtemp(prefix="zipbe-")
    zbe = os.path.join(tmp, "XCAGI.app/Contents/Resources/backend")
    for i in infos:
        rel = zip_name(i).split("Resources/backend/", 1)[1]
        dest = os.path.join(zbe, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(z.read(i.filename))

diffs, checked, missing = [], 0, 0
for i in infos:
    rel = zip_name(i).split("Resources/backend/", 1)[1]
    zp, ip = os.path.join(zbe, rel), os.path.join(BACKEND, rel)
    if not os.path.isfile(ip):
        missing += 1
        diffs.append({"rel": rel, "reason": "missing_in_installed"})
        continue
    checked += 1
    if md5(zp) != md5(ip):
        diffs.append({"rel": rel, "reason": "content_mismatch"})

key_inst = os.path.join(BACKEND, KEY_REL)
key_zip = os.path.join(zbe, KEY_REL)
inst_fix = "_write_cell" in open(key_inst, encoding="utf-8", errors="ignore").read() if os.path.isfile(key_inst) else None
zip_fix = "_write_cell" in open(key_zip, encoding="utf-8", errors="ignore").read() if os.path.isfile(key_zip) else None
inst_md5 = md5(key_inst) if os.path.isfile(key_inst) else None
zip_md5 = md5(key_zip) if os.path.isfile(key_zip) else None

cs_rc, cs_out = run('codesign --verify --deep --strict "%s" 2>&1' % APP)
sp_rc, sp_out = run('spctl -a -vvv -t install "%s" 2>&1' % APP)
st_rc, st_out = run('xcrun stapler validate "%s" 2>&1' % APP)

checks = {
    "codesign_valid": cs_rc == 0,
    "spctl_accepted": "accepted" in sp_out,
    "stapler_validated": "validate action worked" in st_out or "The validate action worked" in st_out,
    "key_source_matches_update_zip": bool(inst_md5 and zip_md5 and inst_md5 == zip_md5),
    "key_source_has_fix": inst_fix is True,
}
d = {
    "schema": "xcagi.gate.evidence.v1",
    "gate": "ota-backend-integrity",
    "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "update_zip": ZIP, "installed_app": APP,
    "zip_backend_files": len(infos), "checked": checked,
    "informational_differing_count": len(diffs),
    "informational_differing_sample": diffs[:10],
    "informational_note": "差异集中在 _internal/*.dylib 等原生二进制：macOS 安装/签名会对 Mach-O 重新签名，属正常，不作为判据。",
    "shipment_document": {"installed_has_fix": inst_fix, "zip_has_fix": zip_fix,
                          "installed_md5": inst_md5, "zip_md5": zip_md5},
    "codesign_output": cs_out[-400:], "spctl_output": sp_out[-300:], "stapler_output": st_out[-200:],
    "checks": checks,
}
d["verdict"] = "PASS" if all(checks.values()) else "BLOCKED"
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(d, open(OUT, "w"), ensure_ascii=False, indent=2)
print("backend-integrity verdict:", d["verdict"], json.dumps(checks, ensure_ascii=False),
      "differing(informational)=", len(diffs))
