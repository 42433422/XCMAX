"""Host SDK runner for bundled manifest-driven employees."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from app.mod_sdk.errors import BOUNDARY_ERRORS


class ManifestEmployeeRuntime:
    """One host runtime per pack; never share its identity, policy or manifest path."""

    def __init__(
        self,
        *,
        module_file,
        employee_id,
        label,
        system_prompt,
        sections,
        logger,
        fallback_unknown_handler=False,
    ):
        self.module_file = module_file
        self.employee_id = employee_id
        self.label = label
        self.system_prompt = system_prompt
        self.sections = sections
        self.logger = logger
        self.fallback_unknown_handler = fallback_unknown_handler
        self._DISPATCH = {
            "echo": self._handle_echo,
            "llm_md": self._handle_llm_md,
            "webhook": self._handle_webhook,
            "agent": self._handle_agent,
        }

    def _ok(
        self,
        data: Any,
        *,
        warnings: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "summary": ""
            if data is None
            else (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))[:4000],
            "items": data
            if isinstance(data, list)
            else ([] if data is None else [data] if not isinstance(data, dict) else [data]),
            "warnings": list(warnings or []),
            "error": "",
            "meta": dict(meta or {}),
        }

    def _err(
        self,
        msg: str,
        *,
        warnings: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": False,
            "summary": msg[:400],
            "items": [],
            "warnings": list(warnings or []),
            "error": msg[:1000],
            "meta": dict(meta or {}),
        }

    def _manifest_path(self) -> Optional[Path]:
        here = Path(self.module_file).resolve()
        for parent in (here.parent, *here.parents):
            cand = parent / "manifest.json"
            if cand.is_file():
                return cand
        return None

    def _load_manifest(self) -> Optional[Dict[str, Any]]:
        mp = self._manifest_path()
        if not mp:
            return None
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _v2(self, manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not isinstance(manifest, dict):
            return {}
        v2 = manifest.get("employee_config_v2")
        return v2 if isinstance(v2, dict) else {}

    def _agent_model(self, v2: Dict[str, Any]) -> Dict[str, Any]:
        cog: Any = v2.get("cognition") if isinstance(v2.get("cognition"), dict) else {}
        agent: Any = cog.get("agent") if isinstance(cog.get("agent"), dict) else {}
        model: Any = agent.get("model") if isinstance(agent.get("model"), dict) else {}
        return {
            "system_prompt": str(agent.get("system_prompt") or "").strip(),
            "max_tokens": int(model.get("max_tokens") or 4000),
            "temperature": float(
                model.get("temperature") if model.get("temperature") is not None else 0.2
            ),
        }

    def _actions(self, v2: Dict[str, Any]) -> Dict[str, Any]:
        a: Any = v2.get("actions") if isinstance(v2.get("actions"), dict) else {}
        return cast(Dict[str, Any], a)

    def _handlers(self, actions: Dict[str, Any]) -> List[str]:
        raw: Any = actions.get("handlers") if isinstance(actions.get("handlers"), list) else []
        return [str(h).strip() for h in raw if isinstance(h, str) and str(h).strip()]

    async def _handle_echo(
        self, payload: Dict[str, Any], _ctx: Dict[str, Any], _v2: Dict[str, Any]
    ) -> Dict[str, Any]:
        return self._ok({"echo": payload}, meta={"handler": "echo"})

    async def _handle_llm_md(
        self, payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]
    ) -> Dict[str, Any]:
        call_llm = ctx.get("call_llm")
        if not callable(call_llm):
            summary = [
                f"# {self.label} 执行方案",
                "",
                "宿主未注入 ctx.call_llm，本次以离线方案模式运行。",
                "",
                "## 输入",
                json.dumps(payload or {}, ensure_ascii=False, indent=2)[:3000],
                "",
                "## 下一步",
                "- 在宿主上下文注入 call_llm 后，可由 llm_md 生成完整 Markdown 结果。",
                "- 也可通过 payload.handler=echo 获取原始输入回显。",
            ]
            return self._ok(
                "\n".join(summary),
                warnings=["ctx.call_llm unavailable; returned offline plan"],
                meta={"handler": "llm_md", "offline": True},
            )
        cfg: Any = self._agent_model(v2)
        sys_prompt = cfg["system_prompt"] or self.system_prompt
        if "##" not in sys_prompt:
            sys_prompt = sys_prompt + "\n\n请用 Markdown 输出，固定章节：\n" + self.sections
        user_msg = json.dumps(payload or {}, ensure_ascii=False)[:6000]
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ]
        try:
            res = await asyncio.wait_for(
                call_llm(messages, max_tokens=cfg["max_tokens"], temperature=cfg["temperature"]),
                timeout=120.0,
            )
        except TimeoutError:
            return self._err("LLM 调用超时（120s）", meta={"handler": "llm_md"})
        except BOUNDARY_ERRORS as e:
            self.logger.exception("call_llm raised")
            return self._err("LLM 调用异常：" + str(e)[:300], meta={"handler": "llm_md"})
        if not isinstance(res, dict) or not res.get("ok"):
            return self._err(
                str((res or {}).get("error") or "LLM 调用失败")[:400], meta={"handler": "llm_md"}
            )
        content = str(res.get("content") or "").strip()
        return self._ok(content, meta={"handler": "llm_md", "max_tokens": cfg["max_tokens"]})

    async def _handle_webhook(
        self, payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]
    ) -> Dict[str, Any]:
        http_post = ctx.get("http_post")
        if not callable(http_post):
            return self._err(
                "ctx.http_post 不可用：宿主未注入 HTTP 能力", meta={"handler": "webhook"}
            )
        cfg: Any = (
            self._actions(v2).get("webhook")
            if isinstance(self._actions(v2).get("webhook"), dict)
            else {}
        )
        url = str(cfg.get("url") or "").strip()
        if not url:
            return self._err("actions.webhook.url 未配置", meta={"handler": "webhook"})
        try:
            r = await asyncio.wait_for(http_post(url, json_body=payload or {}), timeout=30.0)
        except TimeoutError:
            return self._err("webhook 超时（30s）", meta={"handler": "webhook", "url": url})
        except BOUNDARY_ERRORS as e:
            return self._err(
                "webhook 异常：" + str(e)[:300], meta={"handler": "webhook", "url": url}
            )
        if not isinstance(r, dict) or not r.get("ok"):
            return self._err(
                str((r or {}).get("error") or f"HTTP {(r or {}).get('status')}"),
                meta={"handler": "webhook", "url": url},
            )
        return self._ok(
            {"status": r.get("status"), "text": r.get("text")},
            meta={"handler": "webhook", "url": url},
        )

    async def _handle_agent(
        self, payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]
    ) -> Dict[str, Any]:
        runner = ctx.get("agent_runner")
        if runner is None:
            return self._err(
                "ctx.agent_runner 未注入，请确认 modstore_server 版本", meta={"handler": "agent"}
            )
        cfg: Any = self._agent_model(v2)
        task = (
            payload.get("task")
            or payload.get("message")
            or payload.get("input")
            or json.dumps(payload or {}, ensure_ascii=False)[:2000]
        )
        sys_prompt = cfg["system_prompt"] or self.system_prompt
        try:
            result = await asyncio.wait_for(
                runner.run(task, system_prompt=sys_prompt),
                timeout=300.0,
            )
        except TimeoutError:
            return self._err("agent 执行超时（300s）", meta={"handler": "agent"})
        except BOUNDARY_ERRORS as e:
            self.logger.exception("agent run raised")
            return self._err("agent 执行异常：" + str(e)[:300], meta={"handler": "agent"})
        if not result.get("ok"):
            return self._err(
                str(result.get("error") or "agent 失败"),
                meta={"handler": "agent", "rounds": result.get("rounds", 0)},
            )
        return self._ok(
            result.get("summary") or "",
            meta={
                "handler": "agent",
                "rounds": result.get("rounds", 0),
                "tools_used": [t.get("tool") for t in (result.get("tool_calls") or [])],
            },
        )

    async def run(self, payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        self.logger.info(
            "employee run payload_field_count=%d",
            len(payload or {}),
        )
        payload = payload or {}
        ctx = ctx or {}
        manifest = self._load_manifest()
        v2 = self._v2(manifest)
        if not v2:
            return self._err(
                "manifest.employee_config_v2 缺失或不可读，无法决定行为",
                meta={"employee_id": self.employee_id},
            )
        handlers = self._handlers(self._actions(v2))
        if not handlers:
            return self._err(
                "manifest.employee_config_v2.actions.handlers 未声明；请在打包时显式声明 echo / llm_md / webhook 之一",
                meta={"employee_id": self.employee_id},
            )
        requested = str(payload.get("handler") or "").strip() if isinstance(payload, dict) else ""
        chosen = requested if requested in handlers else handlers[0]
        if self.fallback_unknown_handler:
            if chosen not in self._DISPATCH:
                if "agent" in handlers and chosen != "agent":
                    chosen = "agent"
                elif "llm_md" in self._DISPATCH:
                    chosen = "llm_md"
                elif "echo" in self._DISPATCH:
                    chosen = "echo"
        fn = self._DISPATCH.get(chosen)
        if fn is None:
            return self._err(
                f"不支持的 handler：{chosen}（支持：{sorted(self._DISPATCH.keys())}）",
                meta={"employee_id": self.employee_id, "declared_handlers": handlers},
            )
        out: Dict[str, Any] = await fn(payload, ctx, v2)
        if isinstance(out, dict):
            meta = out.setdefault("meta", {})
            if isinstance(meta, dict):
                meta.setdefault("declared_handlers", handlers)
                meta.setdefault("chosen_handler", chosen)
        return out
