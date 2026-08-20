# mypy: disable-error-code="arg-type, attr-defined, index, misc, no-any-return, union-attr, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.mod_scaffold_runner")


async def run_employee_ai_scaffold_async(
    db: _facade().Session,
    user: _facade().User,
    *,
    brief: str,
    replace: bool = True,
    provider: _facade().Optional[str] = None,
    model: _facade().Optional[str] = None,
    publish_to_catalog: bool = True,
) -> _facade().Dict[str, _facade().Any]:
    """
    生成 employee_pack 并导入用户库。商店执行器仍读 CatalogItem；此处产物用于本地库与「员工制作」页继续上架。

    :param publish_to_catalog: 默认 True，保持向后兼容（CLI / 旧脚手架直接调用时仍会写 ``packages.json``
        与 ``catalog_items``）。工作台「做员工」流水线会传 False，仅在 ``library/<pid>`` 落本地工作目录，
        让用户在 ModAuthoring / 员工编辑器里检查后再点 ``/api/workbench/employee-publish`` 发布。
    """
    brief = (brief or "").strip()
    if len(brief) < 3:
        return {"ok": False, "error": "描述过短"}
    from modstore_server.csv_tabular_runtime import is_csv_full_read, is_csv_generate
    from modstore_server.employee_brief_utils import extract_routing_brief
    from modstore_server.excel_tabular_runtime import (
        is_excel_full_read,
        is_excel_generate,
    )
    from modstore_server.pdf_extract_runtime import is_pdf_full_read, is_pdf_generate
    from modstore_server.txt_extract_runtime import is_txt_full_read, is_txt_generate
    from modstore_server.word_extract_runtime import is_word_full_extract
    from modstore_server.word_generate_runtime import is_word_generate

    rb = extract_routing_brief({"brief": brief}, fallback=brief)
    if is_csv_full_read(rb) or is_csv_generate(rb):
        return {
            "ok": False,
            "error": "CSV 读取/生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_excel_full_read(rb) or is_excel_generate(rb):
        return {
            "ok": False,
            "error": "Excel 读取/生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_txt_full_read(rb) or is_txt_generate(rb):
        return {
            "ok": False,
            "error": "TXT 员工必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_pdf_full_read(rb) or is_pdf_generate(rb):
        return {
            "ok": False,
            "error": "PDF 员工必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_word_full_extract(rb):
        return {
            "ok": False,
            "error": "Word 全量提取必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    if is_word_generate(rb):
        return {
            "ok": False,
            "error": "Word 生成必须走资产/direct_python 管线；请在工作台重新制作员工（勿使用 LLM 通用脚手架）",
        }
    prov, mdl, err = await _facade().resolve_llm_provider_model_auto(db, user, provider, model)
    if err:
        return {"ok": False, "error": err}
    api_key, _ = _facade().resolve_api_key(db, user.id, prov)
    if not api_key:
        return {"ok": False, "error": "该供应商未配置可用 API Key（平台或 BYOK）"}
    base = (
        _facade().resolve_base_url(db, user.id, prov)
        if prov in _facade().OAI_COMPAT_OPENAI_STYLE_PROVIDERS
        else None
    )
    msgs = [
        {"role": "system", "content": _facade().SYSTEM_PROMPT_EMPLOYEE},
        {"role": "user", "content": brief},
    ]
    result = await _facade().chat_dispatch(
        prov, api_key=api_key, base_url=base, model=mdl, messages=msgs, max_tokens=6000
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "upstream error"}
    manifest, perr = _facade().parse_employee_pack_llm_json(str(result.get("content") or ""))
    if perr or not manifest:
        return {"ok": False, "error": perr or "无法解析模型输出"}
    from modstore_server.employee_ai_scaffold import (
        _is_template_brief,
        _validate_skill_quality,
    )

    _v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    _cognition = _v2.get("cognition") if isinstance(_v2.get("cognition"), dict) else {}
    _skills = _cognition.get("skills") if isinstance(_cognition.get("skills"), list) else []
    _emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    _label = str(_emp.get("label") or manifest.get("name") or "").strip()
    _desc = str(manifest.get("description") or "").strip()
    _poor_briefs = sum(
        (
            1
            for sk in _skills
            if isinstance(sk, dict) and _is_template_brief(str(sk.get("brief") or ""))
        )
    )
    if _poor_briefs > 0 and len(_skills) > 0:
        _retry_prompt = f"""上一次生成的员工技能描述质量不足，包含模板化套话。请重新为以下技能生成具体的、有业务语义的 brief 描述。\n每个 brief 必须说明：该技能做什么、处理什么输入、输出什么结果。不要使用'围绕...执行...相关任务'这种套话。\n只输出 JSON 数组，不要 markdown 围栏：\n[{{"name":"技能id","brief":"具体描述"}}]\n\n技能列表：{_facade().json.dumps([{"name": sk.get("name"), "brief": sk.get("brief")} for sk in _skills if isinstance(sk, dict)], ensure_ascii=False)}\n员工名称：{_label}\n员工描述：{_desc}"""
        try:
            _retry_result = await _facade().chat_dispatch(
                prov,
                api_key=api_key,
                base_url=base,
                model=mdl,
                messages=[{"role": "user", "content": _retry_prompt}],
                max_tokens=2000,
            )
            if _retry_result.get("ok"):
                import re as _re

                _retry_raw = _re.sub(
                    "^```(?:json)?\\s*",
                    "",
                    (_retry_result.get("content") or "").strip(),
                    flags=_re.I,
                )
                _retry_raw = _re.sub("\\s*```\\s*$", "", _retry_raw).strip()
                _retry_skills = _facade().json.loads(_retry_raw)
                if isinstance(_retry_skills, list):
                    _name_to_brief = {}
                    for rsk in _retry_skills:
                        if isinstance(rsk, dict):
                            _rn = str(rsk.get("name") or "").strip()
                            _rb = str(rsk.get("brief") or "").strip()
                            if _rn and _rb and (not _is_template_brief(_rb)):
                                _name_to_brief[_rn] = _rb
                    for sk in _skills:
                        if isinstance(sk, dict):
                            _sn = str(sk.get("name") or "").strip()
                            if _sn in _name_to_brief:
                                sk["brief"] = _name_to_brief[_sn]
                    _cognition["skills"] = _validate_skill_quality(
                        _skills, label=_label, description=_desc
                    )
                    _v2["cognition"] = _cognition
                    manifest["employee_config_v2"] = _v2
        except RECOVERABLE_ERRORS:
            _cognition["skills"] = _validate_skill_quality(_skills, label=_label, description=_desc)
            _v2["cognition"] = _cognition
            manifest["employee_config_v2"] = _v2
    pid = str(manifest.get("id") or "").strip()
    lib = _facade().modstore_library_path()
    if (lib / pid).is_dir() and (not replace):
        return {"ok": False, "error": f"包 {pid} 已存在，请传 replace=true 覆盖"}
    raw_zip = _facade().build_employee_pack_zip(pid, manifest)
    with _facade().tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        tmp.write(raw_zip)
        tmp_path = _facade().Path(tmp.name)
    try:
        dest = _facade().import_zip(tmp_path, lib, replace=replace)
    except (ValueError, FileExistsError) as e:
        return {"ok": False, "error": str(e)}
    finally:
        tmp_path.unlink(missing_ok=True)
    _facade().add_user_mod(user.id, dest.name)
    saved_package: _facade().Dict[str, _facade().Any] = {}
    if publish_to_catalog:
        with _facade().tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(raw_zip)
            pkg_tmp_path = _facade().Path(tmp.name)
        try:
            from modstore_server.catalog_store import append_package
            from modstore_server.models import CatalogItem

            rec = {
                "id": pid,
                "name": str(manifest.get("name") or pid),
                "version": str(manifest.get("version") or "1.0.0"),
                "description": str(manifest.get("description") or ""),
                "artifact": "employee_pack",
                "industry": str(manifest.get("industry") or "通用"),
                "release_channel": "stable",
                "commerce": {"mode": "free", "price": 0},
                "license": {"type": "personal", "verify_url": None},
            }
            saved_package = append_package(rec, pkg_tmp_path)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pid).first()
            if not row:
                row = CatalogItem(pkg_id=pid, author_id=user.id)
                db.add(row)
            row.version = saved_package.get("version") or rec["version"]
            row.name = saved_package.get("name") or rec["name"]
            row.description = saved_package.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.industry = saved_package.get("industry") or rec["industry"]
            row.stored_filename = saved_package.get("stored_filename") or ""
            row.sha256 = saved_package.get("sha256") or ""
            db.commit()
        finally:
            pkg_tmp_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "id": dest.name,
        "path": str(dest),
        "manifest": manifest,
        "package": saved_package,
        "published": bool(publish_to_catalog and saved_package),
    }
