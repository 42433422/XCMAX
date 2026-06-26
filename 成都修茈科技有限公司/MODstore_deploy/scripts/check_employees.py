#!/usr/bin/env python3
import json
import os
import sys

old_base = "/root/成都修茈科技有限公司/MODstore_deploy"
new_base = "/root/modstore-git/MODstore_deploy"

pkg_json = os.path.join(old_base, "modstore_server/catalog_data/packages.json")
if os.path.isfile(pkg_json):
    with open(pkg_json) as f:
        pkgs = json.load(f)
    emps = [p for p in pkgs if p.get("artifact") == "employee_pack"]
    print(f"Total employee packs in packages.json: {len(emps)}")
    for e in emps:
        print(f"  - {e.get('pkg_id', e.get('id', '?'))}")
else:
    print(f"packages.json not found at {pkg_json}")

print("\n=== Library manifests ===")
for lib_dir in [os.path.join(old_base, "library"), os.path.join(new_base, "modstore_library")]:
    if os.path.isdir(lib_dir):
        for name in sorted(os.listdir(lib_dir)):
            mf = os.path.join(lib_dir, name, "manifest.json")
            if os.path.isfile(mf):
                with open(mf) as f:
                    m = json.load(f)
                if m.get("artifact") == "employee_pack":
                    print(f"  {lib_dir}/{name}: id={m.get('id')}, name={m.get('name')}")

print("\n=== DB catalog_items ===")
try:
    import subprocess

    r = subprocess.run(
        [
            "psql",
            "-h",
            "127.0.0.1",
            "-p",
            "5433",
            "-U",
            "modstore",
            "-d",
            "modstore",
            "-t",
            "-A",
            "-c",
            "SELECT pkg_id, name FROM catalog_items WHERE artifact='employee_pack' ORDER BY pkg_id",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PGPASSWORD": "modstore"},
    )
    if r.stdout.strip():
        for line in r.stdout.strip().split("\n"):
            print(f"  DB: {line}")
    else:
        print("  No employee packs in DB")
except Exception as e:
    print(f"  DB query failed: {e}")
