"""Rebuild test-qa-runner.xcemp at version from yuangon employee.yaml."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]  # MODstore_deploy
REPO = ROOT.parent  # 成都修茈科技有限公司
modstore = ROOT / "modstore_server"
yu = REPO / "yuangon" / "quality-and-docs" / "test-qa-runner" / "employee.yaml"
src = modstore / "market_files" / "test-qa-runner-1.0.0.xcemp"
out = modstore / "catalog_data" / "files" / "test-qa-runner-2.0.3.xcemp"
out_mf = modstore / "market_files" / "test-qa-runner-2.0.3.xcemp"

with yu.open(encoding="utf-8") as f:
    y = yaml.safe_load(f)
name = str(y["name"]).strip()
domain = str(y["domain"]).strip()
ver = str(y.get("version", "2.0.3")).strip().strip('"').strip("'")
deps = y.get("depends_on") or []
if not isinstance(deps, list):
    deps = []

with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    with zipfile.ZipFile(src, "r") as z:
        z.extractall(td_path)
    mpath = td_path / "test-qa-runner" / "manifest.json"
    m = json.loads(mpath.read_text(encoding="utf-8"))
    m["version"] = ver
    m["name"] = name
    m["description"] = domain
    emp = m.get("employee")
    if isinstance(emp, dict):
        emp["label"] = name
    v2 = m.get("employee_config_v2")
    if isinstance(v2, dict):
        ident = v2.get("identity")
        if isinstance(ident, dict):
            ident["version"] = ver
            ident["name"] = name
            ident["description"] = domain
            v2["identity"] = ident
        meta = v2.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        meta["framework_version"] = "2.0.3"
        meta["aligned_from"] = "yuangon/quality-and-docs/test-qa-runner/employee.yaml"
        v2["metadata"] = meta
        collab = v2.get("collaboration")
        if not isinstance(collab, dict):
            collab = {}
        collab["depends_on"] = list(deps)
        v2["collaboration"] = collab
        cog = v2.get("cognition")
        if isinstance(cog, dict):
            ag = cog.get("agent")
            if isinstance(ag, dict):
                role = ag.get("role")
                if isinstance(role, dict):
                    role["name"] = name
                    role["persona"] = domain
                    ag["role"] = role
                v2["cognition"] = cog
        m["employee_config_v2"] = v2
    m["depends_on"] = list(deps)
    trig = y.get("triggers")
    if isinstance(trig, dict):
        m["triggers"] = trig
    for we in m.get("workflow_employees") or []:
        if isinstance(we, dict) and we.get("id") == "test-qa-runner":
            we["label"] = name
            we["panel_title"] = name
            we["panel_summary"] = domain
    mpath.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z_out:
        for p in sorted(td_path.rglob("*")):
            if p.is_file():
                z_out.write(p, p.relative_to(td_path).as_posix())

shutil.copy2(out, out_mf)
digest = hashlib.sha256(out.read_bytes()).hexdigest()
print("written", out)
print("sha256", digest)
print("size", out.stat().st_size)
