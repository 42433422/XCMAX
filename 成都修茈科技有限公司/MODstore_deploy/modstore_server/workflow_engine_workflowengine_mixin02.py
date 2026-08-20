# mypy: disable-error-code="assignment, attr-defined, import-not-found, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


def _facade():
    return importlib.import_module("modstore_server.workflow_engine")


class _WorkflowEnginePart02Mixin:
    def _execute_variable_set_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        """向上下文写入变量（支持 ``{{ var }}`` 模板）。"""
        _facade().logger.info("执行变量赋值节点: %s", node.name)
        name = str(config.get("name") or "").strip()
        if not name:
            raise ValueError("variable_set 节点缺少 name")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        resolved = _facade().resolve_value(config.get("value"), ctx)
        return {name: resolved}

    def _evaluate_condition(self, condition: str, data: _facade().Dict[str, _facade().Any]) -> bool:
        return _facade().eval_condition(condition, data)

    def _execute_http_request_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        import httpx

        method = str(config.get("method") or "GET").upper()
        url_template = str(config.get("url") or "")
        if not url_template:
            raise ValueError("http_request 节点缺少 url 配置")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        url = _facade().resolve_value(url_template, ctx)
        headers_raw = config.get("headers") or {}
        headers = (
            {k: str(_facade().resolve_value(v, ctx)) for (k, v) in headers_raw.items()}
            if isinstance(headers_raw, dict)
            else {}
        )
        body_raw = config.get("body")
        body = _facade().resolve_value(body_raw, ctx) if body_raw else None
        timeout_s = max(1, min(float(config.get("timeout") or 30), 120))
        retries = max(0, min(int(config.get("retries") or 0), 5))
        allow_http = [
            h.strip() for h in str(config.get("allow_http_domains") or "").split(",") if h.strip()
        ]
        if str(url).startswith("http://"):
            from urllib.parse import urlparse as _urlparse

            domain = _urlparse(str(url)).hostname or ""
            if not any((domain.endswith(d) for d in allow_http)):
                url = str(url).replace("http://", "https://", 1)
        output_var = str(config.get("output_var") or f"http_response_{node.id}")
        last_exc = None
        for attempt in range(retries + 1):
            try:

                async def _do():
                    async with httpx.AsyncClient(timeout=timeout_s) as client:
                        r = await client.request(method, str(url), headers=headers, json=body)
                        r.raise_for_status()
                        return r

                import asyncio

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        resp = pool.submit(
                            lambda: httpx.request(
                                method,
                                str(url),
                                headers=headers,
                                json=body,
                                timeout=timeout_s,
                            )
                        ).result(timeout_s + 5)
                else:
                    resp = loop.run_until_complete(_do())
                result_data = (
                    resp.json() if "json" in (resp.headers.get("content-type") or "") else resp.text
                )
                return {
                    output_var: result_data,
                    "http_status": resp.status_code if hasattr(resp, "status_code") else 200,
                    "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                }
            except RECOVERABLE_ERRORS as exc:
                last_exc = exc
                if attempt < retries:
                    import time as _t

                    _t.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"http_request 节点执行失败（重试 {retries} 次）: {last_exc}")

    def _execute_http_request_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        output_var = str(config.get("output_var") or f"http_response_{node.id}")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未发送真实 HTTP 请求"},
            "http_status": 200,
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_code_execute_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        code = str(config.get("code") or "")
        if not code:
            raise ValueError("code_execute 节点缺少 code 配置")
        output_var = str(config.get("output_var") or "code_result")
        local_ns: _facade().Dict[str, _facade().Any] = {
            "input": dict(data),
            "json": __import__("json"),
            "math": __import__("math"),
            "re": __import__("re"),
        }
        try:
            exec(
                compile(code, f"<workflow_code_{node.id}>", "exec"),
                {"__builtins__": {}},
                local_ns,
            )
            result = local_ns.get("result", local_ns.get("output", None))
            return {
                output_var: result,
                "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
            }
        except RECOVERABLE_ERRORS as exc:
            raise RuntimeError(f"code_execute 节点执行失败: {exc}") from exc

    def _execute_code_execute_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        output_var = str(config.get("output_var") or "code_result")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未执行真实代码"},
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_data_transform_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        transforms = config.get("transforms") or []
        output_var = str(config.get("output_var") or "transform_result")
        result = dict(data)
        for t in transforms:
            t_type = str(t.get("type") or "")
            if t_type == "jsonpath":
                import jsonpath_ng.ext as jp

                expr = jp.parse(str(t.get("path") or "$"))
                matches = [m.value for m in expr.find(result)]
                result = matches[0] if len(matches) == 1 else matches
            elif t_type == "field_map":
                mapping = t.get("mapping") or {}
                result = {
                    str(k): result.get(str(v))
                    for (k, v) in mapping.items()
                    if result.get(str(v)) is not None
                }
            elif t_type == "type_cast":
                field = str(t.get("field") or "")
                target_type = str(t.get("cast_to") or "string")
                val = result.get(field)
                if val is not None:
                    if target_type == "string":
                        result[field] = str(val)
                    elif target_type == "number":
                        result[field] = float(val)
                    elif target_type == "integer":
                        result[field] = int(float(val))
                    elif target_type == "boolean":
                        result[field] = bool(val)
            elif t_type == "array_filter":
                field = str(t.get("field") or "")
                condition = str(t.get("condition") or "")
                arr = result.get(field)
                if isinstance(arr, list) and condition:
                    filtered = []
                    for item in arr:
                        if not isinstance(item, dict):
                            continue
                        try:
                            if _facade().eval_condition(condition, item):
                                filtered.append(item)
                        except RECOVERABLE_ERRORS:
                            pass
                    result[field] = filtered
        if not isinstance(result, dict):
            result = {"value": result}
        return {
            output_var: result,
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_data_transform_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        output_var = str(config.get("output_var") or "transform_result")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未执行真实数据转换"},
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_loop_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        loop_type = str(config.get("loop_type") or "for_each")
        max_iterations = max(1, min(int(config.get("max_iterations") or 100), 1000))
        output_var = str(config.get("output_var") or "loop_result")
        results: list = []
        if loop_type == "for_each":
            items_path = str(config.get("items_path") or "")
            nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
            ctx = {**data, "nodes": nodes_ctx, "global": data, "result": data}
            items = (
                _facade().resolve_value(items_path, ctx) if items_path else data.get("items", [])
            )
            if not isinstance(items, list):
                items = list(items) if items else []
            for idx, item in enumerate(items[:max_iterations]):
                results.append({"loop_index": idx, "loop_item": item})
        elif loop_type == "while":
            condition = str(config.get("condition") or "")
            iteration = 0
            while iteration < max_iterations:
                nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
                ctx = {
                    **data,
                    "nodes": nodes_ctx,
                    "global": data,
                    "result": data,
                    "loop_index": iteration,
                    "loop_item": results[-1] if results else None,
                }
                if condition and (not _facade().eval_condition(condition, ctx)):
                    break
                results.append({"loop_index": iteration, "loop_item": None})
                iteration += 1
        return {
            output_var: results,
            "loop_count": len(results),
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_loop_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        output_var = str(config.get("output_var") or "loop_result")
        return {
            output_var: [{"sandbox": True, "message": "沙盒 Mock：未执行真实循环"}],
            "loop_count": 1,
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_parallel_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        branches = config.get("branches") or []
        output_var = str(config.get("output_var") or "parallel_result")
        results: _facade().Dict[str, _facade().Any] = {}
        for branch in branches:
            branch_name = str(branch.get("name") or f"branch_{len(results)}")
            branch_type = str(branch.get("type") or "pass")
            if branch_type == "pass":
                results[branch_name] = {"status": "completed", "data": dict(data)}
            elif branch_type == "http_request":
                try:
                    sub_result = self._execute_http_request_node(node, data, branch)
                    results[branch_name] = {"status": "completed", "data": sub_result}
                except RECOVERABLE_ERRORS as exc:
                    results[branch_name] = {"status": "failed", "error": str(exc)}
            elif branch_type == "data_transform":
                try:
                    sub_result = self._execute_data_transform_node(node, data, branch)
                    results[branch_name] = {"status": "completed", "data": sub_result}
                except RECOVERABLE_ERRORS as exc:
                    results[branch_name] = {"status": "failed", "error": str(exc)}
            else:
                results[branch_name] = {
                    "status": "skipped",
                    "message": f"未知分支类型: {branch_type}",
                }
        return {
            output_var: results,
            "parallel_count": len(results),
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_parallel_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        output_var = str(config.get("output_var") or "parallel_result")
        return {
            output_var: {
                "sandbox": {
                    "status": "completed",
                    "message": "沙盒 Mock：未执行真实并行",
                }
            },
            "parallel_count": 1,
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_sub_workflow_node(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        sub_workflow_id = config.get("workflow_id")
        if not sub_workflow_id:
            raise ValueError("sub_workflow 节点缺少 workflow_id 配置")
        input_mapping = config.get("input_mapping") or {}
        output_var = str(config.get("output_var") or "sub_workflow_result")
        max_depth = max(1, min(int(config.get("max_depth") or 3), 5))
        current_depth = int(data.get("_sub_workflow_depth") or 0) + 1
        if current_depth > max_depth:
            raise RuntimeError(f"子工作流递归深度超过 {max_depth} 层，已中止")
        nodes_ctx = data.get("nodes") if isinstance(data.get("nodes"), dict) else {}
        ctx = {"nodes": nodes_ctx, "global": data, "result": data}
        sub_input = (
            _facade().resolve_value(input_mapping, ctx)
            if isinstance(input_mapping, dict) and input_mapping
            else dict(data)
        )
        if not isinstance(sub_input, dict):
            sub_input = {"value": sub_input}
        sub_input["_sub_workflow_depth"] = current_depth
        sub_result = _facade().execute_workflow(int(sub_workflow_id), sub_input)
        return {
            output_var: sub_result,
            "sub_workflow_id": int(sub_workflow_id),
            "sub_depth": current_depth,
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }

    def _execute_sub_workflow_mock(
        self,
        node: _facade().WorkflowNode,
        data: _facade().Dict[str, _facade().Any],
        config: _facade().Dict[str, _facade().Any],
    ) -> _facade().Dict[str, _facade().Any]:
        output_var = str(config.get("output_var") or "sub_workflow_result")
        return {
            output_var: {"sandbox": True, "message": "沙盒 Mock：未执行真实子工作流"},
            "sub_workflow_id": config.get("workflow_id"),
            "execution_time": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
