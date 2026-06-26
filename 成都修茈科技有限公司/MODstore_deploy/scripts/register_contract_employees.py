#!/usr/bin/env python3
import json, os, sys, zipfile, shutil, subprocess

BASE = "/root/成都修茈科技有限公司/MODstore_deploy"
LIBRARY = os.path.join(BASE, "library")
CATALOG_STORE = os.path.join(BASE, "modstore_server/catalog_data")
PACKAGES_JSON = os.path.join(CATALOG_STORE, "packages.json")
FILES_DIR = os.path.join(CATALOG_STORE, "files")

CONTRACT_EMPLOYEES = ["ai-contract-advisor", "ai-contract-drafter", "ai-contract-consultant"]


def main():
    os.makedirs(FILES_DIR, exist_ok=True)

    if os.path.isfile(PACKAGES_JSON):
        with open(PACKAGES_JSON) as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            packages = (
                list(raw.values()) if all(isinstance(v, dict) for v in raw.values()) else [raw]
            )
        elif isinstance(raw, list):
            packages = raw
        else:
            packages = []
    else:
        packages = []

    existing_ids = set()
    for p in packages:
        if isinstance(p, dict):
            existing_ids.add(p.get("pkg_id", p.get("id", "")))

    for emp_id in CONTRACT_EMPLOYEES:
        lib_dir = os.path.join(LIBRARY, emp_id)
        mf_path = os.path.join(lib_dir, "manifest.json")

        if not os.path.isfile(mf_path):
            print(f"SKIP {emp_id}: manifest.json not found at {mf_path}")
            continue

        with open(mf_path) as f:
            manifest = json.load(f)

        if manifest.get("artifact") != "employee_pack":
            print(f"SKIP {emp_id}: artifact={manifest.get('artifact')} != employee_pack")
            continue

        print(f"Registering {emp_id}...")

        zip_filename = f"{emp_id}-v{manifest.get('version', '1.0.0')}.xcemp"
        zip_path = os.path.join(FILES_DIR, zip_filename)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{emp_id}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            backend_dir = os.path.join(lib_dir, "backend")
            if os.path.isdir(backend_dir):
                for root, dirs, files in os.walk(backend_dir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        arcname = f"{emp_id}/backend/{os.path.relpath(fpath, backend_dir)}"
                        zf.write(fpath, arcname)

        import hashlib

        with open(zip_path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()

        rec = {
            "pkg_id": emp_id,
            "name": manifest.get("name", emp_id),
            "version": manifest.get("version", "1.0.0"),
            "artifact": "employee_pack",
            "industry": manifest.get("industry", "通用"),
            "description": manifest.get("description", ""),
            "stored_filename": zip_filename,
            "sha256": sha256,
            "author": manifest.get("author", ""),
        }

        if emp_id in existing_ids:
            packages = [
                rec if (p.get("pkg_id", p.get("id", "")) == emp_id) else p
                for p in packages
                if isinstance(p, dict)
            ]
        else:
            packages.append(rec)
            existing_ids.add(emp_id)

        print(
            f"  Written {zip_filename} ({os.path.getsize(zip_path)} bytes, sha256={sha256[:16]}...)"
        )

    with open(PACKAGES_JSON, "w") as f:
        json.dump(packages, f, ensure_ascii=False, indent=2)
    print(
        f"\nUpdated {PACKAGES_JSON} with {len([p for p in packages if isinstance(p, dict) and p.get('artifact') == 'employee_pack'])} employee packs"
    )

    print("\n=== Registering in database ===")
    for emp_id in CONTRACT_EMPLOYEES:
        lib_dir = os.path.join(LIBRARY, emp_id)
        mf_path = os.path.join(lib_dir, "manifest.json")
        if not os.path.isfile(mf_path):
            continue
        with open(mf_path) as f:
            manifest = json.load(f)

        zip_filename = f"{emp_id}-v{manifest.get('version', '1.0.0')}.xcemp"
        sql = f"INSERT INTO catalog_items (pkg_id, name, version, artifact, description, industry, stored_filename, author_id) VALUES ('{emp_id}', '{manifest.get('name', emp_id).replace(chr(39), chr(39)+chr(39))}', '{manifest.get('version', '1.0.0')}', 'employee_pack', '{manifest.get('description', '').replace(chr(39), chr(39)+chr(39))}', '{manifest.get('industry', '通用')}', '{zip_filename}', 2) ON CONFLICT (pkg_id) DO UPDATE SET name=EXCLUDED.name, version=EXCLUDED.version, description=EXCLUDED.description, stored_filename=EXCLUDED.stored_filename;"
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
                "-c",
                sql,
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PGPASSWORD": "modstore"},
        )
        if r.returncode == 0:
            print(f"  DB: {emp_id} registered OK")
        else:
            print(f"  DB: {emp_id} failed: {r.stderr[:200]}")

    print("\nDone! Restarting MODstore...")
    subprocess.run(["systemctl", "restart", "modstore"], capture_output=True)
    print("MODstore restarted.")


if __name__ == "__main__":
    main()
