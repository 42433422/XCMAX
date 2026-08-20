# mypy: disable-error-code="attr-defined, import-not-found, no-any-return, valid-type"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib
from modstore_server.workbench_api_part04_part01_part01 import WorkbenchEdgeTtsBody
from modstore_server.workbench_api_part04_part01_part01 import WorkbenchUnifiedTtsBody


def _facade():
    return importlib.import_module("modstore_server.workbench_api")


def _publish_vibe_skill_via_local_modstore(
    coder: _facade().Any,
    skill_id: str,
    publish_cfg: _facade().Dict[str, _facade().Any],
    *,
    user_id: int,
) -> _facade().Dict[str, _facade().Any]:
    """直接调本 MODstore 的 catalog 上传接口,不用 HTTP 自调来回。

    用 vibe-coding 的 ``SkillPackager`` 打包(它知道 .xcmod 内部结构),
    再走 :func:`catalog_store.append_package` + ``CatalogItem`` 写库。
    """
    try:
        from vibe_coding.agent.marketplace import PublishOptions, SkillPackager
    except ImportError as exc:
        return {"ok": False, "error": f"vibe-coding marketplace 未安装: {exc}"}
    pkg_id = str(publish_cfg.get("pkg_id") or "").strip()
    if not pkg_id:
        return {"ok": False, "error": "publish.pkg_id 必填"}
    artifact_kind = str(publish_cfg.get("artifact") or "mod").strip() or "mod"
    if artifact_kind not in ("mod", "employee_pack"):
        return {"ok": False, "error": f"不支持的 artifact: {artifact_kind}"}
    from modstore_server.autonomy_guard_delegate import evaluate_risk

    risk_decision = evaluate_risk(
        "mod_auto_publish",
        {
            "human_approved": True,
            "approved_by": f"workbench-user:{user_id}",
            "trigger": "explicit_workbench_publish",
        },
        action_id=f"mod-publish:{user_id}:{pkg_id}:{str(publish_cfg.get('version') or '1.0.0')}",
        source="workbench.vibe_code_publish",
    )
    if not risk_decision.allowed:
        return {
            "ok": False,
            "error": "autonomy_guard blocked publish",
            "risk_decision": risk_decision.to_dict(),
        }
    try:
        skill = coder.code_store.get_code_skill(skill_id)
    except KeyError:
        return {"ok": False, "error": f"skill_id 不存在: {skill_id}"}
    options = PublishOptions(
        pkg_id=pkg_id,
        version=str(publish_cfg.get("version") or "1.0.0"),
        name=str(publish_cfg.get("name") or pkg_id),
        description=str(publish_cfg.get("description") or ""),
        price=float(publish_cfg.get("price") or 0.0),
        artifact=artifact_kind,
        industry=str(publish_cfg.get("industry") or "通用"),
        author=f"user-{user_id}",
    )
    try:
        packager = SkillPackager()
        artifact = packager.package_skill(skill, options=options)
    except RECOVERABLE_ERRORS as exc:
        return {"ok": False, "error": f"打包失败: {exc}"}
    try:
        from modstore_server.catalog_store import append_package
        from modstore_server.models import CatalogItem

        rec = {
            "id": pkg_id,
            "name": options.name,
            "version": options.version,
            "description": options.description,
            "artifact": artifact_kind,
            "industry": options.industry,
            "release_channel": "stable",
            "commerce": {
                "mode": "free" if options.price <= 0 else "paid",
                "price": options.price,
            },
            "license": {"type": "personal", "verify_url": None},
        }
        sf3 = _facade().get_session_factory()
        with sf3() as session:
            saved = append_package(rec, _facade().Path(artifact.archive_path))
            row = session.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
            if not row:
                row = CatalogItem(pkg_id=pkg_id, author_id=user_id)
                session.add(row)
            row.version = saved.get("version") or rec["version"]
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = float(options.price)
            row.artifact = artifact_kind
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            session.commit()
            if artifact_kind == "employee_pack":
                try:
                    from modstore_server.employee_asset_pipeline import (
                        mirror_catalog_file_to_market_files,
                    )

                    mirror_catalog_file_to_market_files(row.stored_filename)
                except RECOVERABLE_ERRORS:
                    pass
    except RECOVERABLE_ERRORS as exc:
        return {
            "ok": False,
            "error": f"上架到本地 MODstore 失败: {exc}",
            "artifact": getattr(artifact, "to_dict", lambda: {})(),
        }
    return {
        "ok": True,
        "pkg_id": pkg_id,
        "version": options.version,
        "artifact": getattr(artifact, "to_dict", lambda: {})(),
    }


def _edge_tts_rate_str(rate: float) -> str:
    from modstore_server.edge_tts_service import rate_str_from_float

    return rate_str_from_float(rate)


async def _edge_tts_stream_chunks(text: str, voice: str, rate_str: str):
    from modstore_server.edge_tts_service import stream_audio

    async for data in stream_audio(text, voice, rate_str):
        yield data


@_facade().router.post("/tts", summary="统一 TTS（MiMo → Edge 神经音，返回完整音频）")
async def workbench_unified_tts(
    body: WorkbenchUnifiedTtsBody,
    _user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    """优先小米 MiMo-V2.5 TTS，失败回退 edge-tts；不提供浏览器系统 TTS。"""
    from fastapi.responses import Response

    text = body.text.strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    try:
        from modstore_server.mimo_tts_service import DEFAULT_VOICE as MIMO_VOICE
        from modstore_server.mimo_tts_service import synthesize_mimo_tts_async

        mimo_voice = (body.voice or "").strip() or MIMO_VOICE
        audio, err, meta = await synthesize_mimo_tts_async(text, voice=mimo_voice)
        if audio and (not err):
            mime = str(meta.get("mime") or "audio/wav")
            return Response(
                content=audio,
                media_type=mime,
                headers={
                    "Cache-Control": "no-cache",
                    "X-TTS-Provider": "mimo",
                    "X-TTS-Voice": str(meta.get("voice") or mimo_voice),
                },
            )
    except RECOVERABLE_ERRORS:
        pass
    if _facade()._EDGE_TTS is None:
        raise _facade().HTTPException(
            503,
            "MiMo 与 edge-tts 均不可用。请配置 MIMO_API_KEY 或 pip install edge-tts",
        )
    edge_voice = (body.edge_voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _facade()._edge_tts_rate_str(body.rate)
    try:
        chunks: list[bytes] = []
        async for data in _facade()._edge_tts_stream_chunks(text, edge_voice, rate_str):
            if data:
                chunks.append(data)
        mp3 = b"".join(chunks)
        if not mp3:
            raise RuntimeError("edge-tts empty")
        return Response(
            content=mp3,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-cache",
                "X-TTS-Provider": "edge",
                "X-TTS-Voice": edge_voice,
            },
        )
    except _facade().HTTPException:
        raise
    except RECOVERABLE_ERRORS as exc:
        raise _facade().HTTPException(502, f"TTS 合成失败: {exc}") from exc


@_facade().router.post("/tts/edge", summary="微软在线神经 TTS（edge-tts，返回 MP3）")
async def workbench_edge_tts(
    body: WorkbenchEdgeTtsBody,
    _user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if _facade()._EDGE_TTS is None:
        raise _facade().HTTPException(
            503,
            "服务端未安装 edge-tts。请在部署环境执行: pip install 'modstore[web]' 或 pip install edge-tts",
        )
    text = body.text.strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    voice = (body.voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _facade()._edge_tts_rate_str(body.rate)
    try:
        return _facade().StreamingResponse(
            _facade()._edge_tts_stream_chunks(text, voice, rate_str),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except _facade().HTTPException:
        raise
    except RECOVERABLE_ERRORS as exc:
        raise _facade().HTTPException(502, f"TTS 合成失败: {exc}") from exc


@_facade().router.post("/tts/edge/stream", summary="微软在线神经 TTS（edge-tts，chunked MP3 流）")
async def workbench_edge_tts_stream(
    body: WorkbenchEdgeTtsBody,
    _user: _facade().User = _facade().Depends(_facade()._get_current_user),
):
    if _facade()._EDGE_TTS is None:
        raise _facade().HTTPException(
            503,
            "服务端未安装 edge-tts。请在部署环境执行: pip install 'modstore[web]' 或 pip install edge-tts",
        )
    text = body.text.strip()
    if not text:
        raise _facade().HTTPException(400, "text 不能为空")
    voice = (body.voice or "zh-CN-XiaoxiaoNeural").strip()
    rate_str = _facade()._edge_tts_rate_str(body.rate)
    try:
        return _facade().StreamingResponse(
            _facade()._edge_tts_stream_chunks(text, voice, rate_str),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except _facade().HTTPException:
        raise
    except RECOVERABLE_ERRORS as exc:
        raise _facade().HTTPException(502, f"TTS 合成失败: {exc}") from exc
