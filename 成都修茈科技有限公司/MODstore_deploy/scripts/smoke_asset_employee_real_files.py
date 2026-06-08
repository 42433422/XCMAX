from __future__ import annotations

import asyncio
import io
import importlib.util
import json
import os
import sys
import zipfile
from pathlib import Path


BRIEF = """我要创建一个和现有「太阳鸟考勤员」一模一样的员工包。

员工包基础信息：
- 员工包 ID：taiyangniao-attendance-employee
- 员工名称：太阳鸟考勤员
- 版本：1.0.0
- 类型：employee_pack
- 运行方式：direct_python
- 禁止使用 echo
- 禁止 LLM 编造转换结果
- 用户上传 Excel 后必须真实执行 Python 转换

默认输出路径：424/考勤转换输出.xlsx
默认模板路径：424/考勤-2026-3月份考勤统计表.xlsx
manifest.json 的 actions.handlers 必须是 ["direct_python"]。
请生成完整可打包的 employee_pack。
"""


async def main() -> int:
    from modstore_server import models
    from modstore_server.employee_asset_pipeline import (
        _extract_python_code,
        _validate_generated_convert_py,
        build_rule_spec,
        design_asset_employee_manifest,
        generate_runtime_convert_module,
        materialize_asset_employee_pack,
        prepare_employee_assets,
    )
    from modstore_server.models import User
    from modstore_server.llm_key_resolver import OAI_COMPAT_OPENAI_STYLE_PROVIDERS, resolve_api_key, resolve_base_url
    from modstore_server.mod_scaffold_runner import chat_dispatch

    src = Path(r"e:\FHD\424\钉钉导出来的考勤数据.xlsx")
    template = Path(r"e:\FHD\424\考勤-2026-3月份考勤统计表.xlsx")
    missing = [str(p) for p in (src, template) if not p.is_file()]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, ensure_ascii=False))
        return 2

    raw_files = [
        {"filename": template.name, "content": template.read_bytes()},
        {"filename": src.name, "content": src.read_bytes()},
    ]
    models.init_db()
    sf = models.get_session_factory()
    db = sf()
    user = db.query(User).filter(User.username == "admin").first()
    if user is None:
        user = db.query(User).filter(User.email == "admin").first()
    if user is None:
        user = db.query(User).filter(User.is_admin == True).first()
    if user is None:
        user = db.query(User).first()
    if user is None:
        user = User(username="smoke-admin", email="smoke-admin@example.local", password_hash="x", is_admin=True)
        db.add(user)
        db.commit()
        db.refresh(user)

    try:
        asset_manifest = prepare_employee_assets(session_id="real-files-smoke", user_id=int(user.id), raw_files=raw_files)
        rule_spec = build_rule_spec(BRIEF, asset_manifest)
        provider = (os.environ.get("SMOKE_LLM_PROVIDER") or "deepseek").strip()
        model = (os.environ.get("SMOKE_LLM_MODEL") or "deepseek-chat").strip()
        manifest, manifest_meta = await design_asset_employee_manifest(
            db,
            user,
            brief=BRIEF,
            rule_spec=rule_spec,
            provider=provider,
            model=model,
        )
        generated_convert, runtime_meta = await generate_runtime_convert_module(
            db,
            user,
            brief=BRIEF,
            rule_spec=rule_spec,
            asset_manifest=asset_manifest,
            provider=provider,
            model=model,
        )
        pack_dir, raw_zip = materialize_asset_employee_pack(
            manifest=manifest,
            rule_spec=rule_spec,
            asset_manifest=asset_manifest,
            generated_convert_py=generated_convert,
        )
    finally:
        db.close()

    required = [
        "manifest.json",
        "README.md",
        "build_xcemp.py",
        "backend/blueprints.py",
        "backend/employees/__init__.py",
        "backend/employees/taiyangniao_attendance.py",
        "backend/vendor/taiyangniao_attendance/__init__.py",
        "backend/vendor/taiyangniao_attendance/convert.py",
        "backend/vendor/taiyangniao_attendance/mapper.py",
        "backend/vendor/taiyangniao_attendance/parser.py",
        "backend/vendor/taiyangniao_attendance/rules.py",
        "backend/vendor/taiyangniao_attendance/paths.py",
        "backend/vendor/taiyangniao_attendance/mapping.py",
        "backend/vendor/taiyangniao_attendance/header_resolver.py",
        "backend/templates/424/考勤-2026-3月份考勤统计表.xlsx",
    ]
    missing_required = [p for p in required if not (pack_dir / p).is_file()]

    payload = {
        "action": "convert",
        "file_path": str(src),
        "workspace_root": str(pack_dir),
        "output_relpath": "424/考勤转换输出.xlsx",
        "template_relpath": "424/考勤-2026-3月份考勤统计表.xlsx",
        "use_personnel_roster": True,
        "header_row": 0,
    }

    async def _execute_once(current_pack_dir: Path) -> dict:
        backend = current_pack_dir / "backend"
        for key in list(sys.modules):
            if key == "taiyangniao_attendance" or key.startswith("taiyangniao_attendance."):
                sys.modules.pop(key, None)
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        employee_path = backend / "employees" / "taiyangniao_attendance.py"
        spec = importlib.util.spec_from_file_location("smoke_taiyangniao_employee", employee_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {employee_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return await mod.run(payload, {"workspace_root": str(current_pack_dir)})

    async def _repair_convert(previous_code: str, failure: dict, round_no: int) -> tuple[str | None, dict]:
        models.init_db()
        sf2 = models.get_session_factory()
        db2 = sf2()
        try:
            u2 = db2.query(User).filter(User.username == "admin").first() or db2.query(User).first()
            api_key, _ = resolve_api_key(db2, u2.id, provider)  # type: ignore[union-attr]
            if not api_key:
                return None, {"warning": f"{provider} missing api key"}
            base = resolve_base_url(db2, u2.id, provider) if provider in OAI_COMPAT_OPENAI_STYLE_PROVIDERS else None  # type: ignore[union-attr]
            system = (
                "你是 Python 代码修复器。只输出修复后的 convert.py Python 代码块。"
                "必须保留 convert_file 签名，必须真实读取 src_path/template_path 并保存 output_path。"
                "如果业务映射复杂，最低要求也必须基于模板 workbook 写出一个有效 xlsx 到 output_path，并返回统计信息。"
                "禁止 eval/exec/compile/__import__/subprocess/os.system。"
            )
            user_msg = json.dumps(
                {
                    "round": round_no,
                    "failure": failure,
                    "previous_convert_py": previous_code,
                    "brief": BRIEF,
                    "rule_spec": rule_spec,
                    "source_file": str(src),
                    "template_file": str(template),
                },
                ensure_ascii=False,
            )[:24000]
            out = await chat_dispatch(
                provider,
                api_key=api_key,
                base_url=base,
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                max_tokens=8000,
            )
            if not out.get("ok"):
                return None, {"warning": str(out.get("error") or "")}
            code = _extract_python_code(str(out.get("content") or ""))
            ok, err = _validate_generated_convert_py(code)
            if not ok:
                return None, {"warning": err}
            return code.rstrip() + "\n", {"repaired": True, "round": round_no}
        finally:
            db2.close()

    result = await _execute_once(pack_dir)
    repair_history = []
    current_code = generated_convert or ""
    for round_no in range(1, 4):
        output_path_probe = Path(str(((result.get("items") or [{}])[0] or {}).get("output_path") or ""))
        if result.get("ok") and output_path_probe.is_file():
            break
        repaired, repair_meta = await _repair_convert(current_code, result, round_no)
        repair_history.append(repair_meta)
        if not repaired:
            break
        current_code = repaired
        pack_dir, raw_zip = materialize_asset_employee_pack(
            manifest=manifest,
            rule_spec=rule_spec,
            asset_manifest=asset_manifest,
            generated_convert_py=current_code,
        )
        missing_required = [p for p in required if not (pack_dir / p).is_file()]
        payload["workspace_root"] = str(pack_dir)
        result = await _execute_once(pack_dir)

    output_path = Path(str(((result.get("items") or [{}])[0] or {}).get("output_path") or ""))
    xcemp_path = pack_dir / "taiyangniao-attendance-employee.xcemp"
    try:
        with zipfile.ZipFile(io.BytesIO(raw_zip), "r") as zf:
            xcemp_path.write_bytes(raw_zip)
    except Exception:
        pass
    report = {
        "ok": bool(result.get("ok"))
        and not missing_required
        and output_path.is_file()
        and bool(runtime_meta.get("generated")),
        "pack_dir": str(pack_dir),
        "zip_size": len(raw_zip),
        "missing_required": missing_required,
        "manifest": {
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "handlers": (((manifest.get("employee_config_v2") or {}).get("actions") or {}).get("handlers")),
            "direct_python": (((manifest.get("employee_config_v2") or {}).get("actions") or {}).get("direct_python")),
        },
        "manifest_generation": manifest_meta,
        "runtime_generation": runtime_meta,
        "repair_history": repair_history,
        "execution": result,
        "output_exists": output_path.is_file(),
        "output_path": str(output_path),
        "xcemp_path": str(xcemp_path) if xcemp_path.is_file() else "",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
