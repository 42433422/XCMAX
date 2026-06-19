"""employee_pack 员工实现（MODstore 生成）。

行为按 manifest.employee_config_v2.actions.handlers 分支：
  - echo     → 直接回显 payload，不调 LLM
  - llm_md   → 调 ctx.call_llm 出 Markdown（默认章节：用途/输入/输出/示例/异常）
  - webhook  → 调 ctx.http_post 转发到 actions.webhook.url
若 handlers 为空或不被支持，run 返回 {ok: False, error: ...}，绝不默认走 LLM。
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EMPLOYEE_ID = "security-secrets-guard"
EMPLOYEE_LABEL = "安全密钥守卫"

SYSTEM_PROMPT = "你是 XCAGI 员工「安全密钥守卫」。按 manifest.employee_config_v2.actions.handlers 选择 echo、llm_md、webhook 或 agent 分支执行；先读取 payload 与 manifest 配置，提取关键字段，再调用 ctx 工具；输出统一返回 {ok, summary, items, warnings, error, meta}；信息不足时如实说明，禁止编造数据、密钥或外部执行结果。"

DEFAULT_README_SECTIONS = (
    '## 用途\n'
    '## 输入\n'
    '## 输出\n'
    '## 示例\n'
    '## 异常与边界\n'
)


def _ok(data: Any, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        'ok': True,
        'summary': '' if data is None else (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))[:4000],
        'items': data if isinstance(data, list) else ([] if data is None else [data] if not isinstance(data, dict) else [data]),
        'warnings': list(warnings or []),
        'error': '',
        'meta': dict(meta or {}),
    }


def _err(msg: str, *, warnings: Optional[List[str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        'ok': False,
        'summary': msg[:400],
        'items': [],
        'warnings': list(warnings or []),
        'error': msg[:1000],
        'meta': dict(meta or {}),
    }


def _manifest_path() -> Optional[Path]:
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        cand = parent / 'manifest.json'
        if cand.is_file():
            return cand
    return None


def _load_manifest() -> Optional[Dict[str, Any]]:
    mp = _manifest_path()
    if not mp:
        return None
    try:
        data = json.loads(mp.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _v2(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    v2 = manifest.get('employee_config_v2')
    return v2 if isinstance(v2, dict) else {}


def _agent_model(v2: Dict[str, Any]) -> Dict[str, Any]:
    cog = v2.get('cognition') if isinstance(v2.get('cognition'), dict) else {}
    agent = cog.get('agent') if isinstance(cog.get('agent'), dict) else {}
    model = agent.get('model') if isinstance(agent.get('model'), dict) else {}
    return {
        'system_prompt': str(agent.get('system_prompt') or '').strip(),
        'max_tokens': int(model.get('max_tokens') or 4000),
        'temperature': float(model.get('temperature') if model.get('temperature') is not None else 0.2),
    }


def _actions(v2: Dict[str, Any]) -> Dict[str, Any]:
    a = v2.get('actions') if isinstance(v2.get('actions'), dict) else {}
    return a


def _handlers(actions: Dict[str, Any]) -> List[str]:
    raw = actions.get('handlers') if isinstance(actions.get('handlers'), list) else []
    return [str(h).strip() for h in raw if isinstance(h, str) and str(h).strip()]


async def _handle_echo(payload: Dict[str, Any], _ctx: Dict[str, Any], _v2: Dict[str, Any]) -> Dict[str, Any]:
    return _ok({'echo': payload}, meta={'handler': 'echo'})


async def _handle_llm_md(payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    call_llm = ctx.get('call_llm')
    if not callable(call_llm):
        summary = [
            f'# {EMPLOYEE_LABEL} 执行方案',
            '',
            '宿主未注入 ctx.call_llm，本次以离线方案模式运行。',
            '',
            '## 输入',
            json.dumps(payload or {}, ensure_ascii=False, indent=2)[:3000],
            '',
            '## 下一步',
            '- 在宿主上下文注入 call_llm 后，可由 llm_md 生成完整 Markdown 结果。',
            '- 也可通过 payload.handler=echo 获取原始输入回显。',
        ]
        return _ok('\n'.join(summary), warnings=['ctx.call_llm unavailable; returned offline plan'], meta={'handler': 'llm_md', 'offline': True})
    cfg = _agent_model(v2)
    sys_prompt = cfg['system_prompt'] or SYSTEM_PROMPT
    if '##' not in sys_prompt:
        sys_prompt = sys_prompt + '\n\n请用 Markdown 输出，固定章节：\n' + DEFAULT_README_SECTIONS
    user_msg = json.dumps(payload or {}, ensure_ascii=False)[:6000]
    messages = [
        {'role': 'system', 'content': sys_prompt},
        {'role': 'user', 'content': user_msg},
    ]
    try:
        res = await asyncio.wait_for(
            call_llm(messages, max_tokens=cfg['max_tokens'], temperature=cfg['temperature']),
            timeout=120.0,
        )
    except TimeoutError:
        return _err('LLM 调用超时（120s）', meta={'handler': 'llm_md'})
    except Exception as e:  # noqa: BLE001
        logger.exception('call_llm raised')
        return _err('LLM 调用异常：' + str(e)[:300], meta={'handler': 'llm_md'})
    if not isinstance(res, dict) or not res.get('ok'):
        return _err(str((res or {}).get('error') or 'LLM 调用失败')[:400], meta={'handler': 'llm_md'})
    content = str(res.get('content') or '').strip()
    return _ok(content, meta={'handler': 'llm_md', 'max_tokens': cfg['max_tokens']})


async def _handle_webhook(payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    http_post = ctx.get('http_post')
    if not callable(http_post):
        return _err('ctx.http_post 不可用：宿主未注入 HTTP 能力', meta={'handler': 'webhook'})
    cfg = _actions(v2).get('webhook') if isinstance(_actions(v2).get('webhook'), dict) else {}
    url = str(cfg.get('url') or '').strip()
    if not url:
        return _err('actions.webhook.url 未配置', meta={'handler': 'webhook'})
    try:
        r = await asyncio.wait_for(http_post(url, json_body=payload or {}), timeout=30.0)
    except TimeoutError:
        return _err('webhook 超时（30s）', meta={'handler': 'webhook', 'url': url})
    except Exception as e:  # noqa: BLE001
        return _err('webhook 异常：' + str(e)[:300], meta={'handler': 'webhook', 'url': url})
    if not isinstance(r, dict) or not r.get('ok'):
        return _err(str((r or {}).get('error') or f"HTTP {(r or {}).get('status')}"), meta={'handler': 'webhook', 'url': url})
    return _ok({'status': r.get('status'), 'text': r.get('text')}, meta={'handler': 'webhook', 'url': url})


async def _handle_agent(payload: Dict[str, Any], ctx: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    runner = ctx.get('agent_runner')
    if runner is None:
        return _err('ctx.agent_runner 未注入，请确认 modstore_server 版本', meta={'handler': 'agent'})
    cfg = _agent_model(v2)
    task = (
        payload.get('task') or payload.get('message') or payload.get('input')
        or json.dumps(payload or {}, ensure_ascii=False)[:2000]
    )
    sys_prompt = cfg['system_prompt'] or SYSTEM_PROMPT
    try:
        result = await asyncio.wait_for(
            runner.run(task, system_prompt=sys_prompt),
            timeout=300.0,
        )
    except TimeoutError:
        return _err('agent 执行超时（300s）', meta={'handler': 'agent'})
    except Exception as e:  # noqa: BLE001
        logger.exception('agent run raised')
        return _err('agent 执行异常：' + str(e)[:300], meta={'handler': 'agent'})
    if not result.get('ok'):
        return _err(str(result.get('error') or 'agent 失败'), meta={'handler': 'agent', 'rounds': result.get('rounds', 0)})
    return _ok(
        result.get('summary') or '',
        meta={'handler': 'agent', 'rounds': result.get('rounds', 0),
              'tools_used': [t.get('tool') for t in (result.get('tool_calls') or [])]},
    )


_DISPATCH = {
    'echo': _handle_echo,
    'llm_md': _handle_llm_md,
    'webhook': _handle_webhook,
    'agent': _handle_agent,
}


# ---------------------------------------------------------------------------
# P2 skill：解析 GitHub 原生安全工具报告（gitleaks / Trivy / CodeQL）
# ---------------------------------------------------------------------------

_SECRET_PREVIEW_KEEP = 4  # 明文保留首尾各 4 字符


def _redact_secret(value: str) -> str:
    """脱敏密钥：保留首尾各 4 字符，中间用 *** 代替。空值或过短返回 <redacted>。"""
    if not value or not isinstance(value, str):
        return '<redacted>'
    s = value.strip()
    if len(s) <= _SECRET_PREVIEW_KEEP * 2:
        return '<redacted>'
    return s[:_SECRET_PREVIEW_KEEP] + '***' + s[-_SECRET_PREVIEW_KEEP:]


def _sarif_level_to_severity(level: str) -> str:
    """SARIF level → 通用 severity（high/medium/low）。"""
    lv = (level or '').strip().lower()
    if lv in ('error', 'high'):
        return 'high'
    if lv in ('warning', 'medium'):
        return 'medium'
    return 'low'


def parse_gitleaks_sarif(sarif_data: Any) -> Dict[str, Any]:
    """解析 gitleaks SARIF v2.1.0 报告，提取泄漏项并脱敏。

    输入：SARIF dict（含 runs[].results[]）
    输出：{ok, summary, items, warnings, error, meta}
      items[] 每项：{rule_id, severity, file, start_line, secret_preview, redacted, message}
    """
    _empty_meta = {'skill': 'parse-gitleaks-sarif', 'total': 0, 'severity_counts': {'high': 0, 'medium': 0, 'low': 0}}
    if not isinstance(sarif_data, dict):
        return _err('gitleaks SARIF 报告不是 dict', meta=_empty_meta)
    runs = sarif_data.get('runs')
    if not isinstance(runs, list) or not runs:
        return _ok([], warnings=['SARIF runs 为空，无泄漏项'], meta=_empty_meta)

    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        # 规则索引：ruleId → rule metadata（含 security-severity）
        rules_map: Dict[str, Dict[str, Any]] = {}
        rules = run.get('tool', {}).get('driver', {}).get('rules')
        if isinstance(rules, list):
            for r in rules:
                rid = str(r.get('id') or '')
                if rid:
                    rules_map[rid] = r if isinstance(r, dict) else {}

        results = run.get('results')
        if not isinstance(results, list):
            continue
        for res in results:
            if not isinstance(res, dict):
                continue
            rule_id = str(res.get('ruleId') or 'unknown')
            rule_meta = rules_map.get(rule_id, {})
            # severity：优先 properties.security-severity，其次 level
            props = rule_meta.get('properties') if isinstance(rule_meta.get('properties'), dict) else {}
            sec_sev = str(props.get('security-severity') or '').strip().lower()
            if sec_sev:
                try:
                    sv = float(sec_sev)
                    severity = 'high' if sv >= 7.0 else ('medium' if sv >= 4.0 else 'low')
                except ValueError:
                    severity = _sarif_level_to_severity(str(res.get('level') or ''))
            else:
                severity = _sarif_level_to_severity(str(res.get('level') or ''))

            locs = res.get('locations')
            file_path = ''
            start_line = 0
            if isinstance(locs, list) and locs:
                phys_loc = locs[0].get('physicalLocation') if isinstance(locs[0], dict) else {}
                art = phys_loc.get('artifactLocation') if isinstance(phys_loc, dict) else {}
                file_path = str(art.get('uri') or '')
                region = phys_loc.get('region') if isinstance(phys_loc, dict) else {}
                start_line = int(region.get('startLine') or 0) if isinstance(region, dict) else 0

            # 提取 secret 明文用于脱敏预览（fingerprints 或 partialFingerprints）
            secret_raw = ''
            fps = res.get('partialFingerprints') or res.get('fingerprints')
            if isinstance(fps, dict):
                for _k, _v in fps.items():
                    if _v and isinstance(_v, str) and len(_v) > 8:
                        secret_raw = _v
                        break

            # 提取 message（dict 时取 text，否则转字符串）
            msg_obj = res.get('message')
            if isinstance(msg_obj, dict):
                message = str(msg_obj.get('text') or '')
            else:
                message = str(msg_obj or '')

            items.append({
                'rule_id': rule_id,
                'severity': severity,
                'file': file_path,
                'start_line': start_line,
                'secret_preview': _redact_secret(secret_raw),
                'redacted': not bool(secret_raw),
                'message': message[:300],
            })

    if not items:
        warnings.append('gitleaks SARIF 解析完成，未发现泄漏项')

    severity_counts = {'high': 0, 'medium': 0, 'low': 0}
    for it in items:
        severity_counts[it['severity']] = severity_counts.get(it['severity'], 0) + 1

    return _ok(
        items,
        warnings=warnings,
        meta={
            'skill': 'parse-gitleaks-sarif',
            'total': len(items),
            'severity_counts': severity_counts,
        },
    )


def parse_trivy_report(trivy_data: Any) -> Dict[str, Any]:
    """解析 Trivy JSON 报告，提取容器/依赖漏洞。

    输入：Trivy JSON dict（含 Results[].Vulnerabilities[]）
    输出：{ok, summary, items, warnings, error, meta}
      items[] 每项：{vuln_id, pkg, installed_version, fixed_version, severity, cvss, title, target}
    """
    _empty_meta = {'skill': 'parse-trivy-report', 'total': 0, 'severity_counts': {}}
    if not isinstance(trivy_data, dict):
        return _err('Trivy 报告不是 dict', meta=_empty_meta)
    results = trivy_data.get('Results')
    if not isinstance(results, list) or not results:
        return _ok([], warnings=['Trivy Results 为空，无漏洞'], meta=_empty_meta)

    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        target = str(result.get('Target') or '')
        target_type = str(result.get('Type') or '')
        vulns = result.get('Vulnerabilities')
        if not isinstance(vulns, list):
            continue
        for v in vulns:
            if not isinstance(v, dict):
                continue
            severity = str(v.get('Severity') or 'UNKNOWN').upper()
            # CVSS：取第一个可用的 CVSS 向量分数
            cvss_score: Optional[float] = None
            cvss_list = v.get('CVSS')
            if isinstance(cvss_list, dict):
                for _vendor, _cvss in cvss_list.items():
                    if isinstance(_cvss, dict) and _cvss.get('V3Score') is not None:
                        cvss_score = float(_cvss['V3Score'])
                        break
                    if isinstance(_cvss, dict) and _cvss.get('V2Score') is not None:
                        cvss_score = float(_cvss['V2Score'])
                        break
            items.append({
                'vuln_id': str(v.get('VulnerabilityID') or ''),
                'pkg': str(v.get('PkgName') or ''),
                'installed_version': str(v.get('InstalledVersion') or ''),
                'fixed_version': str(v.get('FixedVersion') or ''),
                'severity': severity,
                'cvss': cvss_score,
                'title': str(v.get('Title') or '')[:200],
                'target': target,
                'target_type': target_type,
            })

    if not items:
        warnings.append('Trivy 解析完成，未发现漏洞')

    severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']
    severity_counts = dict.fromkeys(severity_order, 0)
    for it in items:
        severity_counts[it['severity']] = severity_counts.get(it['severity'], 0) + 1

    return _ok(
        items,
        warnings=warnings,
        meta={
            'skill': 'parse-trivy-report',
            'total': len(items),
            'severity_counts': severity_counts,
        },
    )


def parse_codeql_sarif(sarif_data: Any) -> Dict[str, Any]:
    """解析 CodeQL SARIF v2.1.0 报告，提取代码漏洞告警。

    输入：SARIF dict（含 runs[].results[]）
    输出：{ok, summary, items, warnings, error, meta}
      items[] 每项：{rule_id, severity, file, start_line, message, cwe, rule_name}
    """
    _empty_meta = {'skill': 'parse-codeql-sarif', 'total': 0, 'severity_counts': {'high': 0, 'medium': 0, 'low': 0}}
    if not isinstance(sarif_data, dict):
        return _err('CodeQL SARIF 报告不是 dict', meta=_empty_meta)
    runs = sarif_data.get('runs')
    if not isinstance(runs, list) or not runs:
        return _ok([], warnings=['SARIF runs 为空，无告警'], meta=_empty_meta)

    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        # 规则索引：ruleId → rule metadata（含 name, security-severity, tags/CWE）
        rules_map: Dict[str, Dict[str, Any]] = {}
        rules = run.get('tool', {}).get('driver', {}).get('rules')
        if isinstance(rules, list):
            for r in rules:
                rid = str(r.get('id') or '')
                if rid:
                    rules_map[rid] = r if isinstance(r, dict) else {}

        results = run.get('results')
        if not isinstance(results, list):
            continue
        for res in results:
            if not isinstance(res, dict):
                continue
            rule_id = str(res.get('ruleId') or 'unknown')
            rule_meta = rules_map.get(rule_id, {})

            # severity：CodeQL 用 level（error/warning/note），properties.security-severity 覆盖
            props = rule_meta.get('properties') if isinstance(rule_meta.get('properties'), dict) else {}
            sec_sev = str(props.get('security-severity') or '').strip().lower()
            if sec_sev:
                try:
                    sv = float(sec_sev)
                    severity = 'high' if sv >= 7.0 else ('medium' if sv >= 4.0 else 'low')
                except ValueError:
                    severity = _sarif_level_to_severity(str(res.get('level') or ''))
            else:
                severity = _sarif_level_to_severity(str(res.get('level') or ''))

            # 定位代码位置
            locs = res.get('locations')
            file_path = ''
            start_line = 0
            if isinstance(locs, list) and locs:
                phys_loc = locs[0].get('physicalLocation') if isinstance(locs[0], dict) else {}
                art = phys_loc.get('artifactLocation') if isinstance(phys_loc, dict) else {}
                file_path = str(art.get('uri') or '')
                region = phys_loc.get('region') if isinstance(phys_loc, dict) else {}
                start_line = int(region.get('startLine') or 0) if isinstance(region, dict) else 0

            # 提取 message
            msg_obj = res.get('message')
            if isinstance(msg_obj, dict):
                message = str(msg_obj.get('text') or '')
            elif isinstance(msg_obj, str):
                message = msg_obj
            else:
                message = ''

            # 提取 CWE（从 rule properties.tags）
            cwe = ''
            tags = props.get('tags')
            if isinstance(tags, list):
                for tag in tags:
                    tag_s = str(tag)
                    if tag_s.lower().startswith('cwe-'):
                        cwe = tag_s
                        break

            rule_name = str(rule_meta.get('name') or rule_id)

            items.append({
                'rule_id': rule_id,
                'rule_name': rule_name,
                'severity': severity,
                'file': file_path,
                'start_line': start_line,
                'message': message[:300],
                'cwe': cwe,
            })

    if not items:
        warnings.append('CodeQL SARIF 解析完成，未发现告警')

    severity_counts = {'high': 0, 'medium': 0, 'low': 0}
    for it in items:
        severity_counts[it['severity']] = severity_counts.get(it['severity'], 0) + 1

    return _ok(
        items,
        warnings=warnings,
        meta={
            'skill': 'parse-codeql-sarif',
            'total': len(items),
            'severity_counts': severity_counts,
        },
    )


# skill 名 → parse 函数（同步函数，返回 _ok/_err 结构）
_SKILL_DISPATCH = {
    'skill-parse-gitleaks-sarif': parse_gitleaks_sarif,
    'skill-parse-trivy-report': parse_trivy_report,
    'skill-parse-codeql-sarif': parse_codeql_sarif,
}


async def run(payload: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info('[employee:%s] run keys=%s', EMPLOYEE_ID, list((payload or {}).keys())[:12])
    payload = payload or {}
    ctx = ctx or {}

    # P2 skill 分发：payload.skill 优先于 handler
    # 用于解析 GitHub 原生安全工具报告（gitleaks/Trivy/CodeQL）
    requested_skill = str(payload.get('skill') or '').strip()
    if requested_skill:
        skill_fn = _SKILL_DISPATCH.get(requested_skill)
        if skill_fn is None:
            return _err(
                f"不支持的 skill：{requested_skill}（支持：{sorted(_SKILL_DISPATCH.keys())}）",
                meta={'employee_id': EMPLOYEE_ID, 'requested_skill': requested_skill},
            )
        # 报告数据从 payload.report / payload.data / payload.sarif 取
        report_data = payload.get('report') or payload.get('data') or payload.get('sarif')
        if report_data is None:
            return _err(
                f"payload 缺少 report/data/sarif 字段，无法解析（skill={requested_skill}）",
                meta={'employee_id': EMPLOYEE_ID, 'requested_skill': requested_skill},
            )
        try:
            out = skill_fn(report_data)
        except Exception as e:  # noqa: BLE001
            logger.exception('skill %s raised', requested_skill)
            return _err(
                f"skill {requested_skill} 解析异常：{str(e)[:300]}",
                meta={'employee_id': EMPLOYEE_ID, 'requested_skill': requested_skill},
            )
        if isinstance(out, dict):
            meta = out.setdefault('meta', {})
            if isinstance(meta, dict):
                meta.setdefault('employee_id', EMPLOYEE_ID)
                meta.setdefault('requested_skill', requested_skill)
        return out

    manifest = _load_manifest()
    v2 = _v2(manifest)
    if not v2:
        return _err('manifest.employee_config_v2 缺失或不可读，无法决定行为',
                    meta={'employee_id': EMPLOYEE_ID})
    handlers = _handlers(_actions(v2))
    if not handlers:
        return _err('manifest.employee_config_v2.actions.handlers 未声明；请在打包时显式声明 echo / llm_md / webhook 之一',
                    meta={'employee_id': EMPLOYEE_ID})
    requested = str(payload.get('handler') or '').strip() if isinstance(payload, dict) else ''
    chosen = requested if requested in handlers else handlers[0]
    fn = _DISPATCH.get(chosen)
    if fn is None:
        return _err(f"不支持的 handler：{chosen}（支持：{sorted(_DISPATCH.keys())}）",
                    meta={'employee_id': EMPLOYEE_ID, 'declared_handlers': handlers})
    out = await fn(payload, ctx, v2)
    if isinstance(out, dict):
        meta = out.setdefault('meta', {})
        if isinstance(meta, dict):
            meta.setdefault('declared_handlers', handlers)
            meta.setdefault('chosen_handler', chosen)
    return out
