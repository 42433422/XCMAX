/**
 * 浏览器端从 Mod manifest 快照 + workflow_employees 单条 JSON 生成 employee_pack zip，
 * 与 modstore_server.employee_pack_export 行为对齐，供 API 不可用时兜底。
 */
import { strToU8, zipSync } from 'fflate'

const ID_RE = /^[a-z0-9][a-z0-9._-]*$/

export function normalizeModId(s: unknown): string | null {
  const x = String(s || '')
    .trim()
    .toLowerCase()
  if (!x || !ID_RE.test(x)) return null
  return x
}

function slugId(raw: unknown, fallback: string): string {
  let x = String(raw || '')
    .trim()
    .toLowerCase()
  x = x.replace(/[^a-z0-9._-]+/g, '-')
  x = x.replace(/-+/g, '-').replace(/^-|-$/g, '')
  if (!x) x = fallback
  if (x && !/^[a-z0-9]/i.test(x)) x = `x${x}`
  if (!ID_RE.test(x)) x = fallback
  return x.slice(0, 48)
}

function validateEmployeePackManifest(data: any): string[] {
  const errors: string[] = []
  const mid = data?.id
  if (!mid || typeof mid !== 'string' || !mid.trim()) errors.push('缺少非空字符串字段 id')
  else if (!ID_RE.test(mid.trim())) errors.push('id 建议使用小写字母、数字、点、下划线、连字符，且不以连字符开头')
  for (const key of ['name', 'version']) {
    const v = data[key]
    if (v == null || (typeof v === 'string' && !v.trim())) errors.push(`建议填写非空 ${key}`)
  }
  const art = String(data.artifact || 'mod').toLowerCase()
  if (art !== 'employee_pack') errors.push('artifact 须为 employee_pack')
  const emp = data.employee
  if (!emp || typeof emp !== 'object') errors.push('employee_pack 须包含 employee 对象')
  else if (!String(emp.id || '').trim()) errors.push('employee.id 不能为空')
  const scope = String(data.scope || 'global')
    .trim()
    .toLowerCase()
  if (!['global', 'host'].includes(scope)) errors.push('scope 仅支持 global 或 host（host 为二期预留）')
  return errors
}

export function buildEmployeePackManifestFromWorkflow(
  modId: unknown,
  modManifest: any,
  wfEntry: any,
  workflowIndex = 0,
): { manifest: Record<string, unknown> | null; error: string } {
  const mid = normalizeModId(modId)
  if (!mid) return { manifest: null, error: 'Mod id 无效' }

  const wf = wfEntry && typeof wfEntry === 'object' && !Array.isArray(wfEntry) ? wfEntry : {}
  const wfRawId = String(wf.id || '').trim()
  const wfSlug = normalizeModId(wfRawId) || slugId(wfRawId, `emp${workflowIndex}`)
  let packId = wfSlug === mid ? mid : `${mid}-${wfSlug}`
  if (packId.length > 48) packId = packId.slice(0, 48)
  if (!ID_RE.test(packId)) packId = mid

  const nameSrc = String(
    wf.label || wf.panel_title || modManifest?.name || packId,
  ).trim()
  const name = (nameSrc.slice(0, 200) || packId).trim() || packId
  const ver = String(modManifest?.version != null ? modManifest.version : '1.0.0')
    .trim() || '1.0.0'
  const desc = String(
    wf.panel_summary || wf.description || modManifest?.description || '',
  )
    .trim()
    .slice(0, 4000)

  const empId = normalizeModId(String(wf.id || '').trim()) || wfSlug
  const label = (String(wf.label || name).trim() || empId).slice(0, 200)
  const capsIn = wf.capabilities
  const caps = []
  if (Array.isArray(capsIn)) {
    for (const x of capsIn) {
      if (typeof x === 'string' && x.trim()) caps.push(x.trim().slice(0, 128))
    }
  }

  const manifest = {
    id: packId,
    name,
    version: ver,
    author: String(modManifest?.author || '').trim(),
    description: desc,
    artifact: 'employee_pack',
    scope: 'global',
    dependencies:
      modManifest?.dependencies && typeof modManifest.dependencies === 'object'
        ? modManifest.dependencies
        : { xcagi: '>=1.0.0' },
    employee: {
      id: empId,
      label,
      capabilities: caps,
    },
  }

  const ve = validateEmployeePackManifest(manifest)
  if (ve.length) return { manifest: null, error: `manifest 校验: ${ve.join('; ')}` }
  return { manifest, error: '' }
}

/**
 * @returns {{ blob: Blob, packId: string }}
 */
export function buildEmployeePackZipFromPanel({
  modId,
  workflowIndex,
  modManifest,
  workflowJsonText,
}: {
  modId: string
  workflowIndex: number | string
  modManifest: any
  workflowJsonText: string
}) {
  if (!String(modId || '').trim()) throw new Error('缺少 Mod id')
  let wfEntry
  try {
    wfEntry = JSON.parse(workflowJsonText || '{}')
  } catch {
    throw new Error('workflow_employees JSON 无法解析')
  }
  if (!wfEntry || typeof wfEntry !== 'object' || Array.isArray(wfEntry)) {
    throw new Error('workflow 条目须为 JSON 对象（非数组）')
  }
  const mod = modManifest && typeof modManifest === 'object' ? modManifest : {}
  const { manifest, error } = buildEmployeePackManifestFromWorkflow(
    modId.trim(),
    mod,
    wfEntry,
    Number(workflowIndex) || 0,
  )
  if (error || !manifest) throw new Error(error || '无法生成 manifest')

  const packId = String(manifest.id || '').trim()
  const body = `${JSON.stringify(manifest, null, 2)}\n`
  const zipBytes = zipSync({ [`${packId}/manifest.json`]: strToU8(body) }, { level: 6 })
  const blob = new Blob([zipBytes as unknown as BlobPart], { type: 'application/zip' })
  return { blob, packId }
}

function sanitizePackId(raw = '') {
  const norm = normalizeModId(String(raw || '').trim())
  if (norm) return norm
  return slugId(String(raw || '').trim(), 'employee-pack')
}

/**
 * V2 配置转 employee_pack manifest（浏览器端兜底导出专用）
 */
export interface BuildEmployeePackV2Args {
  config: any
  packId?: string
  industry?: string
  price?: number
  author?: string
}

export function buildEmployeePackManifestFromV2({
  config,
  packId = '',
  industry = '',
  price = 0,
  author = '',
}: BuildEmployeePackV2Args) {
  const c = config && typeof config === 'object' ? config : {}
  const identity = c.identity && typeof c.identity === 'object' ? c.identity : {}
  const collaboration = c.collaboration && typeof c.collaboration === 'object' ? c.collaboration : {}
  const wf = collaboration.workflow && typeof collaboration.workflow === 'object' ? collaboration.workflow : {}
  const wfEmployees = Array.isArray(c.workflow_employees) ? c.workflow_employees : []
  const idFromConfig = sanitizePackId(identity.id || '')
  const finalPackId = sanitizePackId(packId || idFromConfig || identity.name || 'employee-pack')

  const workflowId = Number.parseInt(String(wf.workflow_id || 0), 10)
  const capabilities = []
  if (c.perception) capabilities.push('perception')
  if (c.memory) capabilities.push('memory')
  if (c.cognition) capabilities.push('cognition')
  if (c.actions) capabilities.push('actions')
  if (c.management) capabilities.push('management')
  capabilities.push('collaboration')

  const manifest = {
    id: finalPackId,
    name: String(identity.name || finalPackId).trim() || finalPackId,
    version: String(identity.version || '1.0.0').trim() || '1.0.0',
    author: String(author || identity.author || '').trim(),
    description: String(identity.description || '').trim(),
    artifact: 'employee_pack',
    scope: 'global',
    employee: {
      id: String(identity.id || finalPackId).trim() || finalPackId,
      label: String(identity.name || finalPackId).trim() || finalPackId,
      capabilities,
      workflow_id: Number.isFinite(workflowId) ? workflowId : 0,
    },
    workflow_employees: wfEmployees,
    employee_config_v2: c,
    commerce: {
      industry: String(industry || c?.commerce?.industry || '通用').trim() || '通用',
      price: Number.isFinite(Number(price)) ? Number(price) : Number(c?.commerce?.price || 0) || 0,
    },
    metadata: {
      exported_by: 'employee_pack_client_export_v2',
      exported_at: new Date().toISOString(),
    },
  }
  return { manifest, packId: finalPackId }
}

// ── 独立 CLI / zipapp 内嵌模板（与后端 employee_pack_standalone_template.py 对齐）─────────

function _standaloneMainPy(packId: string): string {
  return `\
"""
zipapp 入口 — 让 .xcemp 同时是可执行 zip。

用法：
    python ${packId}.xcemp info
    python ${packId}.xcemp validate
    python ${packId}.xcemp run [--input task.json] [--llm]
"""
import os, runpy, sys, zipfile

_zp = sys.argv[0] if os.path.isfile(sys.argv[0]) else __file__
try:
    with zipfile.ZipFile(_zp) as _zf:
        _pack_id = next(n.split("/")[0] for n in _zf.namelist() if n.endswith("/manifest.json"))
except Exception:
    _pack_id = "${packId}"

sys.argv[0] = f"{_pack_id}.standalone.cli"
runpy.run_module(f"{_pack_id}.standalone.cli", run_name="__main__")
`
}

function _standaloneCliPy(packId: string, employeeId: string): string {
  return `\
"""独立 CLI 入口 — 从 employee_pack .xcemp 中运行。"""
from __future__ import annotations
import argparse, json, sys

PACK_ID = "${packId}"
EMPLOYEE_ID = "${employeeId}"

def _get_runner():
    from ${packId}.standalone import runner as _r
    return _r

def cmd_info(_args):
    r = _get_runner()
    manifest = r.load_manifest()
    if manifest is None:
        print("ERROR: 无法读取 manifest.json", file=sys.stderr); sys.exit(1)
    print(f"id      : {manifest.get('id', '?')}")
    print(f"name    : {manifest.get('name', '?')}")
    print(f"version : {manifest.get('version', '?')}")
    print(f"desc    : {str(manifest.get('description',''))[:120]}")
    emp = manifest.get("employee") or {}
    print(f"employee: {emp.get('id','?')} / {emp.get('label','?')}")
    handlers = (manifest.get("actions") or {}).get("handlers") or []
    print(f"handlers: {', '.join(handlers) if handlers else '(none)'}")

def cmd_validate(_args):
    r = _get_runner()
    ok, issues = r.validate()
    for i in issues:
        print(f"  - {i}")
    if ok:
        print("validate: OK"); sys.exit(0)
    else:
        print("validate: FAIL", file=sys.stderr); sys.exit(1)

def cmd_run(args):
    task_input: dict = {}
    if args.input:
        try:
            with open(args.input, encoding="utf-8") as f:
                task_input = json.load(f)
        except Exception as exc:
            print(f"ERROR: 读取 --input 失败: {exc}", file=sys.stderr); sys.exit(1)
    r = _get_runner()
    result = r.run(task_input, use_llm=args.llm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(prog=f"python {PACK_ID}.xcemp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info"); sub.add_parser("validate")
    run_p = sub.add_parser("run")
    run_p.add_argument("--input", "-i", default=None)
    run_p.add_argument("--llm", action="store_true")
    args = parser.parse_args()
    {"info": cmd_info, "validate": cmd_validate, "run": cmd_run}[args.cmd](args)

if __name__ == "__main__":
    main()
`
}

function _standaloneRunnerPy(packId: string): string {
  return `\
"""manifest 加载 + handler 路由。"""
from __future__ import annotations
import json, os, sys, zipfile
from typing import Any, Dict, List, Optional, Tuple

PACK_ID = "${packId}"

def _zip_path():
    zp = sys.argv[0] if os.path.isfile(sys.argv[0]) else None
    if zp: return zp
    for part in reversed(sys.path):
        if part.endswith(".xcemp") and os.path.isfile(part): return part
    return None

def load_manifest():
    zp = _zip_path()
    if zp:
        try:
            with zipfile.ZipFile(zp) as zf:
                return json.loads(zf.read(f"${packId}/manifest.json").decode("utf-8"))
        except Exception: pass
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in [os.path.join(here, "..", "manifest.json"), os.path.join(here, "..", "..", "manifest.json")]:
        cand = os.path.normpath(cand)
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as f: return json.load(f)
    return None

def validate():
    issues: List[str] = []
    manifest = load_manifest()
    if manifest is None: return False, ["无法加载 manifest.json"]
    for k in ["id", "name", "version", "artifact", "employee"]:
        if not manifest.get(k): issues.append(f"manifest 缺少字段: {k}")
    if manifest.get("artifact") != "employee_pack": issues.append("artifact 须为 employee_pack")
    emp = manifest.get("employee")
    if isinstance(emp, dict):
        if not emp.get("id"): issues.append("employee.id 不能为空")
    else: issues.append("employee 须为对象")
    handlers = (manifest.get("actions") or {}).get("handlers") or []
    if not handlers: issues.append("actions.handlers 为空（员工无可执行路径）")
    from ${packId}.standalone.handlers.no_llm import run_no_llm_checks
    issues.extend(run_no_llm_checks(manifest))
    return len(issues) == 0, issues

def run(task_input: Dict[str, Any], *, use_llm: bool = False) -> Dict[str, Any]:
    manifest = load_manifest()
    if manifest is None: return {"ok": False, "error": "无法加载 manifest.json"}
    handlers = (manifest.get("actions") or {}).get("handlers") or []
    if use_llm and ("llm_md" in handlers or "agent" in handlers):
        from ${packId}.standalone.handlers.llm_md import run_llm_md
        return run_llm_md(manifest, task_input)
    from ${packId}.standalone.handlers.no_llm import run_no_llm
    return run_no_llm(manifest, task_input)
`
}

function _standaloneNoLlmPy(): string {
  return `\
"""无 LLM 检查 handler。"""
from __future__ import annotations
import os, xml.etree.ElementTree as ET
from typing import Any, Dict, List

def run_no_llm_checks(manifest: Dict[str, Any]) -> List[str]:
    issues: List[str] = []
    actions = manifest.get("actions") or {}
    vibe_ready = actions.get("vibe_edit_ready") or {}
    focus_paths = vibe_ready.get("focus_paths") or []
    root = vibe_ready.get("root") or "."
    for rel in focus_paths:
        if "*" in rel: continue
        full = os.path.normpath(os.path.join(root, rel))
        if not os.path.exists(full): issues.append(f"vibe_edit_ready 声明路径不存在: {rel}")
    for rel in focus_paths:
        if not rel.endswith(".xml") or "*" in rel: continue
        full = os.path.normpath(os.path.join(root, rel))
        if os.path.isfile(full):
            try: ET.parse(full)
            except ET.ParseError as exc: issues.append(f"{rel} XML 格式错误: {exc}")
    cognition = manifest.get("cognition") or (manifest.get("employee_config_v2") or {}).get("cognition") or {}
    sp = (cognition.get("agent") or {}).get("system_prompt") or ""
    if len(sp.strip()) < 50: issues.append("system_prompt 过短（< 50 字），可能为占位内容")
    return issues

def run_no_llm(manifest: Dict[str, Any], task_input: Dict[str, Any]) -> Dict[str, Any]:
    issues = run_no_llm_checks(manifest)
    name = manifest.get("name") or manifest.get("id") or "unknown"
    lines = [f"# 员工包独立检查报告 — {name}", "",
             f"- id: {manifest.get('id','?')}", f"- version: {manifest.get('version','?')}",
             f"- handlers: {', '.join((manifest.get('actions') or {}).get('handlers') or [])}", ""]
    if issues:
        lines.append("## 发现问题")
        lines.extend(f"- {i}" for i in issues)
    else:
        lines.append("## 检查通过，未发现结构性问题。")
    xml_content = task_input.get("xml_content") or task_input.get("sitemap_content")
    if xml_content:
        try: ET.fromstring(xml_content); lines += ["", "## XML 内容校验：通过"]
        except ET.ParseError as exc: issues.append(f"XML 内容格式错误: {exc}"); lines += ["", f"## XML 内容校验：FAIL — {exc}"]
    return {"ok": len(issues) == 0, "mode": "no_llm", "issues": issues, "summary": "\\n".join(lines)}
`
}

function _standaloneLlmMdPy(): string {
  return `\
"""LLM Markdown handler。"""
from __future__ import annotations
import json
from typing import Any, Dict

def run_llm_md(manifest: Dict[str, Any], task_input: Dict[str, Any]) -> Dict[str, Any]:
    cognition = manifest.get("cognition") or (manifest.get("employee_config_v2") or {}).get("cognition") or {}
    agent_cfg = cognition.get("agent") or {}
    sp = (agent_cfg.get("system_prompt") or "").strip()
    if not sp:
        sp = f"你是员工「{manifest.get('name', manifest.get('id','未知'))}」。请处理用户给出的任务并以 Markdown 格式输出结果。"
    model_cfg = agent_cfg.get("model") or {}
    user_msg = json.dumps(task_input, ensure_ascii=False) if task_input else "请对员工包进行自检，输出功能摘要与可改进点。"
    from ..llm_adapter import chat
    result = chat([{"role":"system","content":sp},{"role":"user","content":user_msg}],
                  model=model_cfg.get("model_name"), max_tokens=int(model_cfg.get("max_tokens") or 2048),
                  temperature=float(model_cfg.get("temperature") or 0.3))
    if result.startswith("ERROR:"):
        return {"ok": False, "mode": "llm_md", "error": result, "summary": result}
    return {"ok": True, "mode": "llm_md", "summary": result}
`
}

function _standaloneLlmAdapterPy(): string {
  return `\
"""轻量 LLM 适配器 — 仅依赖 stdlib urllib。"""
from __future__ import annotations
import json, os, urllib.error, urllib.request
from typing import Optional

def _env_key():
    ok = os.environ.get("OPENAI_API_KEY","").strip()
    dk = os.environ.get("DEEPSEEK_API_KEY","").strip()
    cb = os.environ.get("OPENAI_BASE_URL","").strip()
    if ok: return ok, (cb or "https://api.openai.com").rstrip("/")+"/v1/chat/completions", "openai"
    if dk: return dk, "https://api.deepseek.com/v1/chat/completions", "deepseek"
    return None

def chat(messages, *, model=None, max_tokens=2048, temperature=0.3, timeout=60) -> str:
    creds = _env_key()
    if creds is None: return "ERROR: 未设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY"
    api_key, url, provider = creds
    if not model: model = "deepseek-chat" if provider == "deepseek" else "gpt-4o-mini"
    payload = json.dumps({"model":model,"messages":messages,"max_tokens":max_tokens,"temperature":temperature}).encode("utf-8")
    req = urllib.request.Request(url, data=payload,
          headers={"Content-Type":"application/json","Authorization":f"Bearer {api_key}"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        if not choices: return "ERROR: 响应 choices 为空"
        return str(choices[0].get("message",{}).get("content") or "")
    except urllib.error.HTTPError as exc:
        try: detail = exc.read().decode("utf-8","replace")[:400]
        except Exception: detail = str(exc)
        return f"ERROR: HTTP {exc.code} — {detail}"
    except Exception as exc: return f"ERROR: {exc}"
`
}

function _standaloneReadmeMd(packId: string, label: string): string {
  return `# ${label} — 独立 CLI 用法

本 \`.xcemp\` 文件同时是一个 Python zipapp，可直接在本地运行，**不依赖 MODstore 平台**。

## 前提
- Python 3.9+，零第三方依赖（默认路径）
- 需要 LLM 时：设置 \`OPENAI_API_KEY\` 或 \`DEEPSEEK_API_KEY\`

## 命令
\`\`\`bash
python ${packId}.xcemp info
python ${packId}.xcemp validate
python ${packId}.xcemp run
python ${packId}.xcemp run --input task.json
python ${packId}.xcemp run --input task.json --llm
\`\`\`
`
}

/**
 * 用 V2 配置在浏览器内构建 employee_pack zip
 * files 支持额外携带代码/资源，键为 zip 内相对路径。
 *
 * 同时注入 __main__.py + <packId>/standalone/* 使产出的 .xcemp
 * 也是 Python zipapp，与后端 employee_pack_standalone_template.py 对齐。
 */
export function buildEmployeePackZipFromV2({
  config,
  packId = '',
  industry = '',
  price = 0,
  author = '',
  files = {},
}: BuildEmployeePackV2Args & { files?: Record<string, string | Uint8Array> }) {
  const { manifest, packId: finalPackId } = buildEmployeePackManifestFromV2({
    config,
    packId,
    industry,
    price,
    author,
  })
  const errors = validateEmployeePackManifest(manifest)
  if (errors.length) throw new Error(`V2 manifest 校验失败: ${errors.join('; ')}`)

  const employeeId = String((manifest.employee as { id?: string } | undefined)?.id || finalPackId)
  const employeeLabel = String((manifest.employee as { label?: string } | undefined)?.label || finalPackId)

  /** @type {Record<string, Uint8Array>} */
  const zipEntries: Record<string, Uint8Array> = {
    [`${finalPackId}/manifest.json`]: strToU8(`${JSON.stringify(manifest, null, 2)}\n`),
    // ── zipapp 独立 CLI 入口（对平台透明）────────────────────────────────
    ['__main__.py']: strToU8(_standaloneMainPy(finalPackId)),
    [`${finalPackId}/standalone/__init__.py`]: strToU8(''),
    [`${finalPackId}/standalone/cli.py`]: strToU8(_standaloneCliPy(finalPackId, employeeId)),
    [`${finalPackId}/standalone/runner.py`]: strToU8(_standaloneRunnerPy(finalPackId)),
    [`${finalPackId}/standalone/llm_adapter.py`]: strToU8(_standaloneLlmAdapterPy()),
    [`${finalPackId}/standalone/handlers/__init__.py`]: strToU8(''),
    [`${finalPackId}/standalone/handlers/no_llm.py`]: strToU8(_standaloneNoLlmPy()),
    [`${finalPackId}/standalone/handlers/llm_md.py`]: strToU8(_standaloneLlmMdPy()),
    [`${finalPackId}/standalone/fixtures/example_input.json`]: strToU8('{"task":"validate"}\n'),
    [`${finalPackId}/standalone/requirements.txt`]: strToU8(''),
    [`${finalPackId}/standalone/README.md`]: strToU8(_standaloneReadmeMd(finalPackId, employeeLabel)),
  }

  const inputFiles = files && typeof files === 'object' ? files : {}
  for (const [rel, body] of Object.entries(inputFiles)) {
    const clean = String(rel || '').replace(/^\/+/, '').trim()
    if (!clean) continue
    if (body instanceof Uint8Array) zipEntries[`${finalPackId}/${clean}`] = body
    else zipEntries[`${finalPackId}/${clean}`] = strToU8(String(body ?? ''))
  }

  const zipBytes = zipSync(zipEntries, { level: 6 })
  const blob = new Blob([zipBytes as unknown as BlobPart], { type: 'application/zip' })
  return { blob, packId: finalPackId, manifest }
}
