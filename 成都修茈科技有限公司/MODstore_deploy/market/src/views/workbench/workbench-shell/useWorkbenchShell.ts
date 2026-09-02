// 工作台壳层主逻辑：路由目标解析/清单加载与规范化、三栏布局与拖拽调宽、保存与发布动作。
import { onMounted, provide, ref, watch } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type CanvasStage from '../panels/CanvasStage.vue'
import type { useWorkbenchStore } from '../../../stores/workbench'
import type { TargetKind } from '../../../stores/workbench'
import { api } from '../../../api'
import { ApiError } from '../../../infrastructure/http/client'
import { createEmptyEmployeeConfigV2, upgradeLegacyToV2 } from '../../../employeeConfigV2'
import type { LlmStatusResponse } from '../../../domain/llm/types'
import { resolveDefaultEmployeeLlmFromStatusAndCatalog } from '../../../domain/llm/defaultEmployeeLlm'

export function useWorkbenchShell(deps: {
  store: ReturnType<typeof useWorkbenchStore>
  route: RouteLocationNormalizedLoaded
  router: Router
  props: { embedded: boolean; initialTarget: TargetKind }
}) {

const { store, route, router, props } = deps

// Mobile panel tab: 'canvas' | 'left' | 'right'
const mobilePanel = ref<'canvas' | 'left' | 'right'>('canvas')

const canvasRef = ref<InstanceType<typeof CanvasStage> | null>(null)

// ── Target kind from route ───────────────────────────────────────────────────

const VALID_KINDS: TargetKind[] = ['employee', 'workflow', 'mod', 'skill']

function resolveKind(): TargetKind {
  const k = String(route.params.target ?? route.query.focus ?? props.initialTarget)
  return (VALID_KINDS.includes(k as TargetKind) ? k : 'employee') as TargetKind
}

function resolveId(): string | null {
  // route.params.id – from /workbench/shell/employee/:id
  // route.query.id  – explicit ?id= query
  // route.query.packId – set by wb-home make-scene handoff (fromAi=1)
  const id = route.params.id ?? route.query.id ?? route.query.packId ?? null
  return id ? String(id) : null
}

// ── Load target manifest ──────────────────────────────────────────────────────

const loading = ref(false)
const loadError = ref('')

function _snapshotBaseline(id: string, manifest: Record<string, unknown>) {
  try {
    sessionStorage.setItem(`workbench_baseline_manifest_${id}`, JSON.stringify(manifest))
  } catch { /* quota exceeded – ignore */ }
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
}

function firstRecord(v: unknown): Record<string, unknown> {
  return Array.isArray(v) && v[0] && typeof v[0] === 'object' ? v[0] as Record<string, unknown> : {}
}

function firstNonEmpty(...vals: unknown[]): string {
  for (const v of vals) {
    const s = String(v ?? '').trim()
    if (s) return s
  }
  return ''
}

function firstPositiveNumber(...vals: unknown[]): number {
  for (const v of vals) {
    const n = Number(v ?? 0)
    if (Number.isFinite(n) && n > 0) return n
  }
  return 0
}

/** 新建或占位员工：默认厂商/模型与部署侧可用密钥对齐（平台优先） */
async function buildEmptyEmployeeManifestForEditor(): Promise<Record<string, unknown>> {
  try {
    const [statusRaw, catalogRaw] = await Promise.all([
      api.llmStatus().catch(() => null),
      api.llmCatalog(false).catch(() => null),
    ])
    const picked = resolveDefaultEmployeeLlmFromStatusAndCatalog(
      statusRaw as LlmStatusResponse | null,
      catalogRaw as { providers?: Array<{ provider: string; models?: string[] }> } | null,
    )
    return createEmptyEmployeeConfigV2({ model: picked }) as Record<string, unknown>
  } catch {
    return createEmptyEmployeeConfigV2() as Record<string, unknown>
  }
}

function normalizeEmployeePackManifest(
  pack: Record<string, unknown>,
  fallbackId: string,
): { manifest: Record<string, unknown>; displayName: string } {
  const raw = asRecord(pack.manifest ?? pack)
  const rootV2 = asRecord(raw.employee_config_v2)
  const v2Base: Record<string, unknown> = Object.keys(rootV2).length
    ? rootV2
    : Object.keys(asRecord(raw.identity)).length
      ? raw
      : upgradeLegacyToV2(raw)

  const empEntry = firstRecord(raw.workflow_employees)
  const rootEmployee = asRecord(raw.employee)
  const v2Identity = asRecord(v2Base.identity)
  const v2Cognition = asRecord(v2Base.cognition)
  const v2Agent = asRecord(v2Cognition.agent)
  const v2Role = asRecord(v2Agent.role)
  const v2Model = asRecord(v2Agent.model)
  const v2Collab = asRecord(v2Base.collaboration)
  const v2Workflow = asRecord(v2Collab.workflow)

  const identity = {
    ...v2Identity,
    id: firstNonEmpty(v2Identity.id, rootEmployee.id, empEntry.id, raw.id, pack.pack_id, pack.id, fallbackId),
    name: firstNonEmpty(v2Identity.name, rootEmployee.label, rootEmployee.name, empEntry.label, empEntry.name, raw.name, pack.name, fallbackId),
    version: firstNonEmpty(v2Identity.version, raw.version, pack.version, '1.0.0'),
    artifact: firstNonEmpty(v2Identity.artifact, raw.artifact, 'employee_pack'),
    description: firstNonEmpty(v2Identity.description, rootEmployee.description, empEntry.description, raw.description, pack.description),
  }

  const roleName = firstNonEmpty(v2Role.name, rootEmployee.label, rootEmployee.name, empEntry.label, empEntry.name, identity.name)
  const persona = firstNonEmpty(
    v2Role.persona,
    rootEmployee.description,
    empEntry.description,
    raw.description,
    identity.description,
    '专业、高效、亲切',
  )
  const systemPrompt = firstNonEmpty(
    v2Agent.system_prompt,
    empEntry.system_prompt,
    empEntry.panel_summary,
    rootEmployee.system_prompt,
    raw.panel_summary,
    raw.description,
    identity.description,
  )

  const workflowId = firstPositiveNumber(
    v2Workflow.workflow_id,
    empEntry.workflow_id,
    empEntry.workflowId,
    asRecord(raw.workflow_attachment).workflow_id,
    rootEmployee.workflow_id,
    route.query.wfId,
  )

  const rawSkills = Array.isArray(asRecord(v2Base.cognition).skills)
    ? asRecord(v2Base.cognition).skills as unknown[]
    : Array.isArray(raw.skills)
      ? raw.skills as unknown[]
      : Array.isArray(empEntry.skills)
        ? empEntry.skills as unknown[]
        : Array.isArray(asRecord(raw.metadata).suggested_skills)
          ? asRecord(raw.metadata).suggested_skills as unknown[]
          : []

  const cognition = {
    ...v2Cognition,
    agent: {
      ...v2Agent,
      system_prompt: systemPrompt,
      role: {
        ...v2Role,
        name: roleName,
        persona,
        tone: firstNonEmpty(v2Role.tone, 'professional'),
        expertise: Array.isArray(v2Role.expertise) ? v2Role.expertise : [],
      },
      behavior_rules: Array.isArray(v2Agent.behavior_rules) ? v2Agent.behavior_rules : [],
      few_shot_examples: Array.isArray(v2Agent.few_shot_examples) ? v2Agent.few_shot_examples : [],
      model: {
        provider: firstNonEmpty(v2Model.provider, 'auto'),
        model_name: firstNonEmpty(v2Model.model_name, 'auto'),
        temperature: Number.isFinite(Number(v2Model.temperature)) ? Number(v2Model.temperature) : 0.7,
        max_tokens: Number.isFinite(Number(v2Model.max_tokens)) ? Number(v2Model.max_tokens) : 4000,
        top_p: Number.isFinite(Number(v2Model.top_p)) ? Number(v2Model.top_p) : 0.9,
      },
    },
    skills: rawSkills,
  }

  const manifest: Record<string, unknown> = {
    ...v2Base,
    identity,
    cognition,
    collaboration: {
      ...v2Collab,
      workflow: {
        ...v2Workflow,
        workflow_id: workflowId,
        name: firstNonEmpty(v2Workflow.name, asRecord(raw.workflow_attachment).workflow_name, empEntry.workflow_name),
      },
    },
    workflow_employees: Array.isArray(v2Base.workflow_employees)
      ? v2Base.workflow_employees
      : Array.isArray(raw.workflow_employees)
        ? raw.workflow_employees
        : [],
  }

  return { manifest, displayName: String(identity.name || fallbackId) }
}

async function loadTarget(kind: TargetKind, id: string | null) {
  loading.value = true
  loadError.value = ''

  try {
    if (kind === 'employee' && id) {
      // Check for an AI-draft prefill written by EmployeeAiDraftReview.openInAuthoring()
      const prefillRaw = sessionStorage.getItem('modstore_employee_prefill')
      if (prefillRaw) {
        try {
          const prefill = asRecord(JSON.parse(prefillRaw))
          const prefillIdentity = asRecord(prefill.identity)
          const prefillId = String(prefill.id ?? prefillIdentity.id ?? '')
          if (prefillId === id || !prefillId) {
            sessionStorage.removeItem('modstore_employee_prefill')
            const name = String(prefill.name ?? prefillIdentity.name ?? id)
            store.setTarget(kind, id, prefill, name)
            _snapshotBaseline(id, prefill)
            store.loadEligibleWorkflows()
            return
          }
        } catch { /* malformed prefill – fall through to API load */ }
      }

      // Load existing employee pack manifest from dedicated endpoint.
      // listEmployees() only returns lightweight catalog rows (id/name/version/source) — no manifest.
      let pack: Record<string, unknown> | null = null
      try {
        pack = await api.getEmployeeManifest(id) as Record<string, unknown>
      } catch (err) {
        let extra = ''
        if (err instanceof ApiError && err.status === 503) {
          extra = '（503：请在 Network 中查看是同一路由还是 /api/llm/status、/api/llm/catalog 等。）'
        }
        loadError.value = `加载员工包失败：${(err as Error)?.message || String(err)}${extra}`
        pack = null
      }
      if (pack) {
        const { manifest, displayName } = normalizeEmployeePackManifest(pack, id)
        store.setTarget(kind, id, manifest, displayName)
        _snapshotBaseline(id, manifest)
      } else {
        const empty = await buildEmptyEmployeeManifestForEditor()
        store.setTarget(kind, id, empty, id)
        _snapshotBaseline(id, empty)
      }
    } else if (kind === 'employee') {
      // New employee：默认 cognition.agent.model 对齐当前账号可用平台/BYOK 厂商
      store.setTarget('employee', null, await buildEmptyEmployeeManifestForEditor(), '新员工')
    } else {
      // workflow / mod / skill — placeholder targets
      store.setTarget(kind, id, {}, id ?? kind)
    }

    // Pre-load workflow list for the heart node dropdown
    if (kind === 'employee') {
      store.loadEligibleWorkflows()
    }
  } catch (e: unknown) {
    loadError.value = (e as Error)?.message || String(e)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadTarget(resolveKind(), resolveId())
  // If coming from wb-home generation and manifest has no workflow linked, apply the generated wfId
  const wfId = Number(route.query.wfId ?? 0)
  if (wfId > 0) {
    const mf = asRecord(store.target.manifest)
    const collaboration = asRecord(mf.collaboration)
    const workflow = asRecord(collaboration.workflow)
    const curWfId = Number(workflow.workflow_id ?? 0)
    if (curWfId === 0) {
      store.patchManifest('collaboration.workflow.workflow_id', wfId)
    }
  }
  setTimeout(() => canvasRef.value?.fitView(), 200)
})

watch(
  () => [
    route.params.target,
    route.params.id,
    route.query.packId,
    route.query.id,
    route.query.focus,
  ] as const,
  async () => {
    await loadTarget(resolveKind(), resolveId())
    setTimeout(() => canvasRef.value?.fitView(), 200)
  },
)

// ── Target switcher bar (top) ────────────────────────────────────────────────

const TARGET_TABS: { kind: TargetKind; label: string; icon: string }[] = [
  { kind: 'employee', label: '员工', icon: '⚙️' },
  { kind: 'workflow', label: '工作流', icon: '⚡' },
  { kind: 'mod', label: 'Mod 库', icon: '📦' },
  { kind: 'skill', label: '技能', icon: '🔧' },
]

function switchTarget(kind: TargetKind) {
  if (props.embedded) {
    void loadTarget(kind, null)
    return
  }
  router.push({ name: 'workbench-shell', params: { target: kind } })
}

// ── Panels resize ─────────────────────────────────────────────────────────────

const leftWidth = ref(props.embedded ? 260 : 280)
const rightWidth = ref(props.embedded ? 280 : 300)
const sidePanelsCollapsed = ref(false)

function onLeftResizeMouseDown(e: MouseEvent) {
  const win = globalThis as unknown as Window
  const startX = e.clientX
  const startW = leftWidth.value
  const move = (ev: Event) => {
    const me = ev as MouseEvent
    leftWidth.value = Math.max(220, Math.min(480, startW + me.clientX - startX))
  }
  const up = () => {
    win.removeEventListener('mousemove', move)
    win.removeEventListener('mouseup', up)
  }
  win.addEventListener('mousemove', move)
  win.addEventListener('mouseup', up)
}

function onRightResizeMouseDown(e: MouseEvent) {
  const win = globalThis as unknown as Window
  const startX = e.clientX
  const startW = rightWidth.value
  const move = (ev: Event) => {
    const me = ev as MouseEvent
    rightWidth.value = Math.max(240, Math.min(520, startW - me.clientX + startX))
  }
  const up = () => {
    win.removeEventListener('mousemove', move)
    win.removeEventListener('mouseup', up)
  }
  win.addEventListener('mousemove', move)
  win.addEventListener('mouseup', up)
}

function onCanvasLayoutModeChange(mode: 'normal' | 'workflow-focus') {
  // 「工作流画布」沉浸模式：收起左右栏让画布占满（嵌入与非嵌入一致）
  const next = mode === 'workflow-focus'
  if (sidePanelsCollapsed.value === next) return
  sidePanelsCollapsed.value = next
  // 左右栏显隐会改变中心可视区，触发一次适配，避免节点挤在旧视口。
  setTimeout(() => canvasRef.value?.fitView(), 120)
}

// ── Save / publish actions ────────────────────────────────────────────────────

const saving = ref(false)
const saveMsg = ref('')

async function saveEmployee() {
  if (saving.value) return
  saving.value = true
  saveMsg.value = ''
  try {
    const manifest = store.target.manifest
    const identity = manifest.identity as Record<string, unknown> | undefined
    if (!identity?.id || !identity?.name) {
      saveMsg.value = '请先填写员工身份（ID 和名称）'
      return
    }
    const employeeId = String(identity.id || store.target.id || '')
    const res = await api.employeeSaveManifest(manifest, employeeId) as {
      ok?: boolean
      pack_id?: string
      error?: string
      eskill_registered?: number
      eskill_error?: string
      manifest?: Record<string, unknown>
    }
    if (res?.ok) {
      // Update target id
      if (res.pack_id) {
        store.target.id = res.pack_id
      }
      // Apply returned manifest (has eskill_id written back into cognition.skills)
      if (res.manifest && typeof res.manifest === 'object') {
        store.target.manifest = res.manifest as Record<string, unknown>
      }
      const skillMsg = (res.eskill_registered ?? 0) > 0
        ? `，已注册 ${res.eskill_registered} 个 Skill`
        : (res.eskill_error ? '（Skill 注册跳过）' : '')
      saveMsg.value = `配置已保存${skillMsg}`
      store.dirty = false
      store.lastSavedAt = Date.now()
      setTimeout(() => { saveMsg.value = '' }, 4000)
    } else {
      saveMsg.value = '保存失败: ' + (res?.error || '未知错误')
    }
  } catch (e: unknown) {
    saveMsg.value = '保存失败: ' + ((e as Error)?.message || String(e))
  } finally {
    saving.value = false
  }
}

provide('workbenchSaveEmployee', saveEmployee)
provide('workbenchSaving', saving)
provide('workbenchSaveMsg', saveMsg)

// ── Select employee from LeftRail ─────────────────────────────────────────────

async function onSelectEmployee(id: string) {
  await loadTarget('employee', id)
  if (!props.embedded) {
    void router.replace({ name: 'workbench-shell', params: { target: 'employee', id } })
  }
  setTimeout(() => canvasRef.value?.fitView(), 200)
}

// ── Toolbar panel toggles ────────────────────────────────────────────────────

const showPackagePanel = ref(false)
const showTestPanel = ref(false)
const showPublishPanel = ref(false)

  return {
    mobilePanel,
    canvasRef,
    loading,
    loadError,
    resolveKind,
    resolveId,
    normalizeEmployeePackManifest,
    buildEmptyEmployeeManifestForEditor,
    loadTarget,
    TARGET_TABS,
    switchTarget,
    leftWidth,
    rightWidth,
    sidePanelsCollapsed,
    onLeftResizeMouseDown,
    onRightResizeMouseDown,
    onCanvasLayoutModeChange,
    saving,
    saveMsg,
    saveEmployee,
    onSelectEmployee,
    showPackagePanel,
    showTestPanel,
    showPublishPanel,
  }
}
