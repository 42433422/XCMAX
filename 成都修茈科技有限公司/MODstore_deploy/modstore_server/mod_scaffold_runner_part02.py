# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


def global_registered_employee_ids(*, db: _facade().Optional[_facade().Session] = None) -> set[str]:
    """全局员工注册表：编制 duty_roster + catalog_store + DB catalog + 磁盘 _employees + yuangon。"""
    from modstore_server.duty_roster import all_planned_employee_ids

    ids: set[str] = set(all_planned_employee_ids())
    try:
        from modstore_server.catalog_store import employee_pack_records_from_store

        ids.update(employee_pack_records_from_store().keys())
    except Exception:
        _facade()._logger.debug(
            "global_registered_employee_ids: catalog_store skipped", exc_info=True
        )
    if db is not None:
        try:
            from modstore_server.incident_bus import _catalog_employee_ids

            ids.update(_catalog_employee_ids(db))
        except Exception:
            _facade()._logger.debug(
                "global_registered_employee_ids: db catalog skipped", exc_info=True
            )
    try:
        cfg = _facade().load_config()
        lib = _facade().resolved_library(cfg)
        emp_root = _facade().Path(lib) / "_employees"
        if emp_root.is_dir():
            for child in emp_root.iterdir():
                if child.is_dir() and (child / "manifest.json").is_file():
                    ids.add(child.name)
    except Exception:
        pass
    try:
        from modstore_server.daily_employee_briefs import _workspace_repo_root

        yroot = _workspace_repo_root() / "yuangon"
        if yroot.is_dir():
            for yaml_path in yroot.glob("**/employee.yaml"):
                try:
                    import yaml

                    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(data, dict):
                    eid = str(data.get("id") or yaml_path.parent.name).strip()
                    if eid:
                        ids.add(eid)
    except Exception:
        pass
    return ids


def employee_pack_compileall_errors(
    mod_dir: _facade().Path,
) -> _facade().Tuple[_facade().List[str], _facade().List[str]]:
    """对包内全部 .py 做语法编译；返回 (errors, warnings)。"""
    errors: _facade().List[str] = []
    warnings: _facade().List[str] = []
    if not mod_dir.is_dir():
        return (errors, warnings)
    for p in sorted(mod_dir.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            _facade().py_compile.compile(str(p), doraise=True)
        except _facade().py_compile.PyCompileError as e:
            rel = p.relative_to(mod_dir).as_posix()
            errors.append(f"{rel}: {e.msg}")
        except OSError as e:
            rel = p.relative_to(mod_dir).as_posix()
            errors.append(f"{rel}: {e}")
    return (errors, warnings)


def _collect_pack_depends_on_ids(
    manifest: _facade().Dict[str, _facade().Any]
) -> _facade().List[str]:
    deps: _facade().List[str] = []
    seen: set[str] = set()

    def _add(raw: _facade().Any) -> None:
        if not isinstance(raw, list):
            return
        for item in raw:
            eid = str(item).strip()
            if eid and eid not in seen:
                seen.add(eid)
                deps.append(eid)

    _add(manifest.get("depends_on"))
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    collab = v2.get("collaboration") if isinstance(v2.get("collaboration"), dict) else {}
    _add(collab.get("depends_on"))
    return deps


def _collect_pack_skill_paths(
    manifest: _facade().Dict[str, _facade().Any], pack_dir: _facade().Path
) -> _facade().List[str]:
    paths: _facade().List[str] = []
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    cog = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
    for s in cog.get("skills") if isinstance(cog.get("skills"), list) else []:
        if isinstance(s, dict):
            for key in ("path", "file", "skill_path"):
                val = str(s.get(key) or "").strip()
                if val:
                    paths.append(val)
            name = str(s.get("name") or "").strip()
            if name:
                guessed = f"skills/{name}.md" if not name.endswith(".md") else name
                if guessed not in paths:
                    paths.append(guessed)
        elif isinstance(s, str) and s.strip():
            paths.append(s.strip())
    yaml_path = pack_dir / "employee.yaml"
    if yaml_path.is_file():
        try:
            import yaml

            ydata = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(ydata, dict):
                for sk in ydata.get("skills") if isinstance(ydata.get("skills"), list) else []:
                    if isinstance(sk, str) and sk.strip():
                        paths.append(sk.strip())
        except Exception:
            pass
    return paths


def _manifest_validation_stage(pack_dir: _facade().Path) -> _facade().Dict[str, _facade().Any]:
    stage: _facade().Dict[str, _facade().Any] = {"status": "ok", "errors": []}
    (mf, mf_err) = _facade().read_manifest(pack_dir)
    if mf_err or not mf:
        stage["status"] = "fail"
        stage["errors"].append(mf_err or "manifest.json 不可读")
        return stage
    if not str(mf.get("id") or "").strip():
        stage["status"] = "fail"
        stage["errors"].append("manifest 缺少 id")
    if str(mf.get("artifact") or "").strip() not in ("employee_pack", ""):
        art = str(mf.get("artifact") or "")
        if art and art != "employee_pack":
            stage["errors"].append(f"artifact 应为 employee_pack，当前为 {art!r}")
            stage["status"] = "fail"
    emp = mf.get("employee") if isinstance(mf.get("employee"), dict) else {}
    if not str(emp.get("id") or "").strip():
        stage["errors"].append("manifest.employee.id 缺失")
        stage["status"] = "fail"
    v2 = mf.get("employee_config_v2") if isinstance(mf.get("employee_config_v2"), dict) else {}
    ident = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
    for key in ("owner", "area"):
        val = ident.get(key)
        if val is not None and (not isinstance(val, str)):
            stage["errors"].append(f"employee_config_v2.identity.{key} 须为字符串")
            stage["status"] = "fail"
    wp = v2.get("workspace_policy") if isinstance(v2.get("workspace_policy"), dict) else {}
    scope = wp.get("scope_globs") if isinstance(wp.get("scope_globs"), list) else []
    forbidden = wp.get("forbidden_globs") if isinstance(wp.get("forbidden_globs"), list) else []
    overlap = set((str(x) for x in scope)) & set((str(x) for x in forbidden))
    if overlap:
        stage["errors"].append(f"scope_globs 与 forbidden_globs 冲突: {sorted(overlap)[:4]}")
        stage["status"] = "fail"
    actions = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
    handlers = actions.get("handlers")
    if not isinstance(handlers, list) or not handlers:
        stage["errors"].append("employee_config_v2.actions.handlers 为空")
        stage["status"] = "fail"
    yaml_path = pack_dir / "employee.yaml"
    if yaml_path.is_file():
        try:
            import yaml

            ydata = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if isinstance(ydata, dict):
                for req in ("id", "name", "owner", "area"):
                    if not str(ydata.get(req) or "").strip():
                        stage["errors"].append(f"employee.yaml 缺少必填字段 {req}")
                        stage["status"] = "fail"
                yo = ydata.get("owner")
                ya = ydata.get("area")
                if yo is not None and (not isinstance(yo, str)):
                    stage["errors"].append("employee.yaml owner 须为字符串")
                    stage["status"] = "fail"
                if ya is not None and (not isinstance(ya, str)):
                    stage["errors"].append("employee.yaml area 须为字符串")
                    stage["status"] = "fail"
        except Exception as exc:
            stage["errors"].append(f"employee.yaml 解析失败: {exc}")
            stage["status"] = "fail"
    return stage


def _consistency_check_stage(
    pack_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    db: _facade().Optional[_facade().Session] = None,
) -> _facade().Dict[str, _facade().Any]:
    stage: _facade().Dict[str, _facade().Any] = {
        "status": "ok",
        "missing_skills": [],
        "missing_depends": [],
        "warnings": [],
    }
    registered = _facade().global_registered_employee_ids(db=db)
    pack_id = str(manifest.get("id") or pack_dir.name).strip()
    if pack_id:
        registered.add(pack_id)
    for dep in _facade()._collect_pack_depends_on_ids(manifest):
        if dep not in registered:
            stage["missing_depends"].append(dep)
    pack_id_for_skills = str(manifest.get("id") or pack_dir.name).strip()
    yuangon_pack: _facade().Optional[_facade().Path] = None
    try:
        from modstore_server.daily_employee_briefs import _resolve_pack_dir
        from modstore_server.duty_roster import yuangon_area_for_pkg

        area = yuangon_area_for_pkg(pack_id_for_skills)
        if area:
            (_, yuangon_pack) = _resolve_pack_dir(area, pack_id_for_skills)
    except Exception:
        yuangon_pack = None
    for rel in _facade()._collect_pack_skill_paths(manifest, pack_dir):
        rel_norm = rel.lstrip("/")
        candidates = [pack_dir / rel_norm, pack_dir / "skills" / _facade().Path(rel_norm).name]
        if yuangon_pack is not None:
            candidates.append(yuangon_pack / rel_norm)
            candidates.append(yuangon_pack / "skills" / _facade().Path(rel_norm).name)
        if not any((c.is_file() for c in candidates)):
            stage["missing_skills"].append(rel_norm)
    cons_warns = _facade().employee_pack_consistency_warnings(pack_dir)
    if cons_warns:
        stage["warnings"].extend(cons_warns[:12])
    if stage["missing_depends"] or stage["missing_skills"]:
        stage["status"] = "fail"
    return stage


async def _xcemp_validation_stage(
    pack_dir: _facade().Path,
    manifest: _facade().Dict[str, _facade().Any],
    *,
    timeout_seconds: float = 20.0,
) -> _facade().Dict[str, _facade().Any]:
    stage: _facade().Dict[str, _facade().Any] = {
        "status": "ok",
        "errors": [],
        "escalate_to_human": False,
        "package_hash": "",
        "timeout_log": "",
    }
    pack_id = str(manifest.get("id") or pack_dir.name).strip() or "employee-pack"
    try:
        from modstore_server.employee_pack_export import (
            _build_employee_pack_zip_with_source,
            collect_vendor_modules_from_pack,
        )

        vendor = collect_vendor_modules_from_pack(pack_dir) if pack_dir.is_dir() else None
        zip_bytes = _build_employee_pack_zip_with_source(
            pack_id, manifest, None, vendor_modules=vendor
        )
        stage["package_hash"] = _facade().hashlib.sha256(zip_bytes).hexdigest()[:16]
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tf:
            tf.write(zip_bytes)
            tmp_path = tf.name
        try:
            proc = await _facade().asyncio.wait_for(
                _facade().asyncio.create_subprocess_exec(
                    _facade().sys.executable,
                    tmp_path,
                    "validate",
                    stdout=_facade().asyncio.subprocess.PIPE,
                    stderr=_facade().asyncio.subprocess.PIPE,
                ),
                timeout=timeout_seconds,
            )
            (stdout, stderr) = await _facade().asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
            if proc.returncode != 0:
                stage["status"] = "fail"
                out = (stderr or stdout or b"").decode("utf-8", errors="replace")[:500]
                stage["errors"].append(f"validate 退出码 {proc.returncode}: {out}")
        except _facade().asyncio.TimeoutError:
            stage["status"] = "fail"
            stage["timeout_log"] = (
                f"python {pack_id}.xcemp validate 超时（{timeout_seconds}s）；package_hash={stage['package_hash']}"
            )
            stage["errors"].append(stage["timeout_log"])
            stage["escalate_to_human"] = True
        finally:
            try:
                _facade().os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as exc:
        stage["status"] = "fail"
        stage["errors"].append(f"xcemp 构建或验证异常: {exc!s}"[:400])
    return stage


async def run_employee_pack_code_validation_report(
    pack_dir: _facade().Path,
    *,
    db: _facade().Optional[_facade().Session] = None,
    xcemp_timeout_seconds: float = 20.0,
) -> _facade().Dict[str, _facade().Any]:
    """code-validator / skill-code-validation 结构化校验报告（四阶段 JSON）。"""
    pack_dir = _facade().Path(pack_dir)
    employee_id = pack_dir.name if pack_dir.name else ""
    if not pack_dir.is_dir():
        summary = f"员工包根目录不存在或不可读: {pack_dir}"
        return {
            "status": "fail",
            "employee_id": employee_id,
            "manifest_validation": {"status": "fail", "errors": [summary]},
            "python_compile": {"status": "skipped", "warnings": [], "errors": []},
            "consistency_check": {"status": "skipped", "missing_skills": [], "missing_depends": []},
            "xcemp_validation": {"status": "skipped", "errors": [], "escalate_to_human": False},
            "summary": summary,
        }
    (mf, mf_err) = _facade().read_manifest(pack_dir)
    if mf_err or not isinstance(mf, dict):
        mf = {}
    employee_id = str(mf.get("id") or employee_id).strip()
    manifest_validation = _facade()._manifest_validation_stage(pack_dir)
    report: _facade().Dict[str, _facade().Any] = {
        "status": "ok",
        "employee_id": employee_id,
        "manifest_validation": manifest_validation,
        "python_compile": {"status": "ok", "warnings": [], "errors": []},
        "consistency_check": {"status": "ok", "missing_skills": [], "missing_depends": []},
        "xcemp_validation": {"status": "ok", "errors": [], "escalate_to_human": False},
        "summary": "",
    }
    if manifest_validation.get("status") == "fail":
        report["status"] = "fail"
        report["python_compile"]["status"] = "skipped"
        report["consistency_check"]["status"] = "skipped"
        report["xcemp_validation"]["status"] = "skipped"
        report["summary"] = (
            "manifest 校验失败: " + "；".join(manifest_validation.get("errors") or [])[:400]
        )
        return report
    (py_errors, py_warns) = _facade().employee_pack_compileall_errors(pack_dir)
    backend_warns = _facade().mod_compileall_warnings(pack_dir)
    merged_warns = list(dict.fromkeys(py_warns + backend_warns))
    report["python_compile"] = {
        "status": "fail" if py_errors else "ok",
        "warnings": merged_warns,
        "errors": py_errors,
    }
    if py_errors:
        report["status"] = "fail"
    consistency = _facade()._consistency_check_stage(pack_dir, mf, db=db)
    report["consistency_check"] = {
        "status": consistency.get("status"),
        "missing_skills": consistency.get("missing_skills") or [],
        "missing_depends": consistency.get("missing_depends") or [],
        "warnings": consistency.get("warnings") or [],
    }
    if consistency.get("status") == "fail":
        report["status"] = "fail"
    xcemp = await _facade()._xcemp_validation_stage(
        pack_dir, mf, timeout_seconds=xcemp_timeout_seconds
    )
    report["xcemp_validation"] = {
        "status": xcemp.get("status"),
        "errors": xcemp.get("errors") or [],
        "escalate_to_human": bool(xcemp.get("escalate_to_human")),
        "package_hash": xcemp.get("package_hash") or "",
        "timeout_log": xcemp.get("timeout_log") or "",
    }
    if xcemp.get("status") == "fail":
        report["status"] = "fail"
        if xcemp.get("escalate_to_human"):
            try:
                from modstore_server.craft_failure_signals import _employee_escalate_to_human

                if _employee_escalate_to_human("code-validator"):
                    report["xcemp_validation"]["escalate_to_human"] = True
            except Exception:
                report["xcemp_validation"]["escalate_to_human"] = True
    parts: _facade().List[str] = []
    if report["status"] == "ok":
        parts.append("员工包四阶段校验通过")
    else:
        if manifest_validation.get("status") == "fail":
            parts.append("manifest 未通过")
        if report["python_compile"].get("status") == "fail":
            parts.append(f"Python 编译 {len(py_errors)} 处错误")
        if consistency.get("missing_depends"):
            parts.append(f"depends_on 未注册: {', '.join(consistency['missing_depends'][:4])}")
        if consistency.get("missing_skills"):
            parts.append(f"skills 缺失: {', '.join(consistency['missing_skills'][:4])}")
        if xcemp.get("status") == "fail":
            parts.append("xcemp validate 未通过")
    report["summary"] = "；".join(parts) if parts else report["status"]
    return report


def resolve_llm_provider_model(
    db: _facade().Session,
    user: _facade().User,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str], _facade().Optional[str]]:
    """
    返回 (provider, model, error_message)。
    若 body 未传 provider/model，则读用户 default_llm_json。
    """
    prov = (provider or "").strip()
    mdl = (model or "").strip()
    if prov and mdl:
        if prov not in _facade().KNOWN_PROVIDERS:
            return (None, None, f"不支持的供应商: {prov}")
        return (prov, mdl, None)
    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
    prefs: _facade().Dict[str, _facade().Any] = {}
    if raw_pref:
        try:
            loaded = _facade().json.loads(raw_pref)
            if isinstance(loaded, dict):
                prefs = loaded
        except _facade().json.JSONDecodeError:
            prefs = {}
    prov = str(prefs.get("provider") or "").strip()
    mdl = str(prefs.get("model") or "").strip()
    if not prov or prov not in _facade().KNOWN_PROVIDERS or (not mdl):
        return (
            None,
            None,
            "请先在 LLM 设置中选择默认供应商与模型，或在请求中传入 provider 与 model",
        )
    return (prov, mdl, None)


async def resolve_llm_provider_model_auto(
    db: _facade().Session,
    user: _facade().User,
    provider: _facade().Optional[str],
    model: _facade().Optional[str],
) -> _facade().Tuple[_facade().Optional[str], _facade().Optional[str], _facade().Optional[str]]:
    """
    工作台 Auto 语义：显式 provider/model 必须可用；否则优先账户默认，
    默认无 key 时自动切到第一个有 key 且能拿到模型目录的供应商。
    """
    prov = (provider or "").strip()
    mdl = (model or "").strip()
    if prov and mdl:
        if prov not in _facade().KNOWN_PROVIDERS:
            return (None, None, f"不支持的供应商: {prov}")
        (api_key, _) = _facade().resolve_api_key(db, user.id, prov)
        if not api_key:
            return (None, None, f"供应商 {prov} 未配置可用 API Key")
        return (prov, mdl, None)
    from modstore_server.llm_catalog import get_models_for_provider

    async def first_model_id(p: str) -> str:
        try:
            block = await get_models_for_provider(db, user.id, p, force_refresh=False)
        except Exception:
            return ""
        mids = list(block.get("models") or [])
        return str(mids[0]).strip() if mids else ""

    urow = db.query(_facade().User).filter(_facade().User.id == user.id).first()
    raw_pref = ((urow.default_llm_json if urow else None) or "").strip()
    prefs: _facade().Dict[str, _facade().Any] = {}
    if raw_pref:
        try:
            loaded = _facade().json.loads(raw_pref)
            if isinstance(loaded, dict):
                prefs = loaded
        except _facade().json.JSONDecodeError:
            prefs = {}
    pref_p = str(prefs.get("provider") or "").strip()
    pref_m = str(prefs.get("model") or "").strip()
    if pref_p in _facade().KNOWN_PROVIDERS:
        (api_key, _) = _facade().resolve_api_key(db, user.id, pref_p)
        if api_key:
            if pref_m:
                return (pref_p, pref_m, None)
            m0 = await first_model_id(pref_p)
            if m0:
                return (pref_p, m0, None)
    if "xiaomi" in _facade().KNOWN_PROVIDERS:
        (api_key, _) = _facade().resolve_api_key(db, user.id, "xiaomi")
        if api_key:
            m0 = await first_model_id("xiaomi")
            if m0:
                return ("xiaomi", m0, None)
    for p in _facade().KNOWN_PROVIDERS:
        (api_key, _) = _facade().resolve_api_key(db, user.id, p)
        if not api_key:
            continue
        m0 = await first_model_id(p)
        if m0:
            return (p, m0, None)
    return (None, None, "没有找到已配置 API Key 且可用模型目录的 LLM 供应商")
