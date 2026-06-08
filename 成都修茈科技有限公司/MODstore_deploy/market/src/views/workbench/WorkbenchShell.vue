<script setup lang="ts">
import { onMounted, provide, ref, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LeftRail from './panels/LeftRail.vue'
import CanvasStage from './panels/CanvasStage.vue'
import RightRail from './panels/RightRail.vue'
import { useWorkbenchStore } from '../../stores/workbench'
import { useAuthStore } from '../../stores/auth'
import { api } from '../../api'
import { ApiError } from '../../infrastructure/http/client'
import type { TargetKind } from '../../stores/workbench'
import { createEmptyEmployeeConfigV2, upgradeLegacyToV2 } from '../../employeeConfigV2'
import type { LlmStatusResponse } from '../../domain/llm/types'
import { resolveDefaultEmployeeLlmFromStatusAndCatalog } from '../../domain/llm/defaultEmployeeLlm'
import { useBreakpoint } from '../../composables/useBreakpoint'

const store = useWorkbenchStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const { isMobile } = useBreakpoint()

// Mobile panel tab: 'canvas' | 'left' | 'right'
const mobilePanel = ref<'canvas' | 'left' | 'right'>('canvas')

const props = withDefaults(defineProps<{
  embedded?: boolean
  initialTarget?: TargetKind
}>(), {
  embedded: false,
  initialTarget: 'employee',
})

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
          const prefill = JSON.parse(prefillRaw) as Record<string, any>
          const prefillId = String(prefill.id ?? prefill.identity?.id ?? '')
          if (prefillId === id || !prefillId) {
            sessionStorage.removeItem('modstore_employee_prefill')
            const name = String(prefill.name ?? prefill.identity?.name ?? id)
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
    const mf = store.target.manifest as Record<string, any>
    const curWfId = Number(mf?.collaboration?.workflow?.workflow_id ?? 0)
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
</script>

<template>
  <div class="wb-shell" :class="{ 'wb-shell--embedded': embedded }">
    <!-- Top bar -->
    <header v-if="!embedded" class="wb-topbar">
      <!-- Left: branding + target tabs -->
      <div class="wb-topbar-left">
        <RouterLink
          class="wb-logo wb-logo-home-link"
          :to="{ name: 'workbench-home' }"
          title="返回工作台首页（三档对话）"
          aria-label="返回工作台首页（三档对话）"
        >
          <span class="wb-logo-return" aria-hidden="true">←</span>
          XCAGI <span class="wb-logo-badge">工作台</span>
        </RouterLink>
        <nav class="wb-target-tabs">
          <button
            v-for="tab in TARGET_TABS"
            :key="tab.kind"
            class="wb-target-tab"
            :class="{ 'wb-target-tab--active': store.target.kind === tab.kind }"
            @click="switchTarget(tab.kind)"
          >
            <span>{{ tab.icon }}</span>
            <span>{{ tab.label }}</span>
          </button>
        </nav>
      </div>

      <!-- Center: current target name + dirty indicator -->
      <div class="wb-topbar-center">
        <span class="wb-target-name">{{ store.target.name || '未命名' }}</span>
        <span v-if="store.dirty" class="wb-dirty">● 未保存</span>
        <span v-if="store.target.id" class="wb-target-id">ID: {{ store.target.id }}</span>
      </div>

      <!-- Right: action buttons -->
      <div class="wb-topbar-right">
        <span v-if="saveMsg" class="wb-save-msg" :class="{ 'wb-save-msg--ok': saveMsg.startsWith('配置') }">
          {{ saveMsg }}
        </span>
        <button class="wb-btn" @click="showPackagePanel = !showPackagePanel">上传打包</button>
        <button class="wb-btn" @click="showTestPanel = !showTestPanel">测试审核</button>
        <button class="wb-btn wb-btn--primary" :disabled="saving" @click="saveEmployee">
          {{ saving ? '保存中…' : '保存' }}
        </button>
        <button class="wb-btn wb-btn--publish" @click="showPublishPanel = !showPublishPanel">
          发布上架
        </button>
        <span class="wb-user">{{ auth.username || '—' }}</span>
      </div>
    </header>

    <!-- Loading / Error overlay -->
    <div v-if="loading" class="wb-loading">
      <span class="wb-loading-spinner">●</span> 加载中…
    </div>
    <div v-else-if="loadError" class="wb-error">加载失败：{{ loadError }}</div>

    <!-- Three-column body -->
    <div v-else class="wb-body" :class="{ 'wb-body--canvas-focus': sidePanelsCollapsed, 'wb-body--mobile': isMobile }">
      <!-- Left rail -->
      <div v-show="!sidePanelsCollapsed && (!isMobile || mobilePanel === 'left')" class="wb-col wb-col--left" :style="isMobile ? {} : { width: leftWidth + 'px' }">
        <LeftRail @select-employee="onSelectEmployee" />
      </div>

      <!-- Resize handle left -->
      <div
        v-show="!sidePanelsCollapsed && !isMobile"
        class="wb-resize"
        @mousedown="onLeftResizeMouseDown"
      />

      <!-- Center canvas -->
      <div v-show="!isMobile || mobilePanel === 'canvas'" class="wb-col wb-col--center">
        <CanvasStage ref="canvasRef" @layout-mode-change="onCanvasLayoutModeChange" />
      </div>

      <!-- Resize handle right -->
      <div
        v-show="!sidePanelsCollapsed && !isMobile"
        class="wb-resize"
        @mousedown="onRightResizeMouseDown"
      />

      <!-- Right rail -->
      <div v-show="!sidePanelsCollapsed && (!isMobile || mobilePanel === 'right')" class="wb-col wb-col--right" :style="isMobile ? {} : { width: rightWidth + 'px' }">
        <RightRail />
      </div>
    </div>

    <!-- Mobile bottom tab bar -->
    <nav v-if="isMobile && !loading && !loadError" class="wb-mobile-tabbar">
      <button class="wb-mobile-tab" :class="{ 'wb-mobile-tab--active': mobilePanel === 'left' }" @click="mobilePanel = 'left'">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="2" width="5" height="14" rx="1.5"/><rect x="9" y="2" width="7" height="6" rx="1.5"/></svg>
        <span>员工</span>
      </button>
      <button class="wb-mobile-tab" :class="{ 'wb-mobile-tab--active': mobilePanel === 'canvas' }" @click="mobilePanel = 'canvas'">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><circle cx="9" cy="9" r="7"/><circle cx="9" cy="9" r="2.5" fill="currentColor" stroke="none"/></svg>
        <span>画布</span>
      </button>
      <button class="wb-mobile-tab" :class="{ 'wb-mobile-tab--active': mobilePanel === 'right' }" @click="mobilePanel = 'right'">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.4"><rect x="2" y="10" width="7" height="6" rx="1.5"/><rect x="11" y="2" width="5" height="14" rx="1.5"/></svg>
        <span>配置</span>
      </button>
    </nav>

    <!-- Package panel drawer -->
    <transition name="drawer">
      <div v-if="showPackagePanel" class="wb-drawer">
        <div class="wb-drawer-header">
          <span>上传打包</span>
          <button class="wb-drawer-close" @click="showPackagePanel = false">✕</button>
        </div>
        <div class="wb-drawer-body">
          <pre class="drawer-json">{{ JSON.stringify(store.target.manifest, null, 2) }}</pre>
        </div>
      </div>
    </transition>

    <!-- Test panel drawer -->
    <transition name="drawer">
      <div v-if="showTestPanel" class="wb-drawer">
        <div class="wb-drawer-header">
          <span>测试审核</span>
          <button class="wb-drawer-close" @click="showTestPanel = false">✕</button>
        </div>
        <div class="wb-drawer-body">
          <p v-if="!store.target.id" class="drawer-warn">请先保存员工以获得 ID。</p>
        </div>
      </div>
    </transition>

    <!-- Publish panel drawer -->
    <transition name="drawer">
      <div v-if="showPublishPanel" class="wb-drawer">
        <div class="wb-drawer-header">
          <span>发布上架</span>
          <button class="wb-drawer-close" @click="showPublishPanel = false">✕</button>
        </div>
        <div class="wb-drawer-body">
          <p v-if="!store.target.id" class="drawer-warn">请先保存员工以获得 ID。</p>
        </div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.wb-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: #080f1a;
  color: #e2e8f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
}

.wb-shell--embedded {
  height: 100%;
  min-height: 0;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  background: #050505;
}

/* ── Top bar ── */
.wb-topbar {
  height: 48px;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  background: rgba(8, 15, 26, 0.98);
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  flex-shrink: 0;
  z-index: 100;
}

.wb-topbar-left, .wb-topbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.wb-topbar-center {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 0;
}

.wb-logo {
  font-size: 14px;
  font-weight: 900;
  color: #6366f1;
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.wb-logo-home-link {
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.wb-logo-return {
  font-size: 13px;
  font-weight: 700;
  color: rgba(148, 163, 184, 0.55);
  transition: color 0.15s ease;
}

.wb-logo-home-link:hover .wb-logo-return {
  color: #a5b4fc;
}

.wb-logo-home-link:hover {
  color: #818cf8;
}

.wb-logo-home-link:focus-visible {
  outline: 2px solid rgba(129, 140, 248, 0.65);
  outline-offset: 3px;
  border-radius: 6px;
}

.wb-logo-badge {
  font-size: 9px;
  font-weight: 700;
  background: rgba(99, 102, 241, 0.15);
  color: #a5b4fc;
  padding: 2px 6px;
  border-radius: 5px;
  border: 1px solid rgba(99, 102, 241, 0.2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  vertical-align: middle;
  margin-left: 4px;
}

.wb-target-tabs {
  display: flex;
  gap: 2px;
}

.wb-target-tab {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 7px;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.wb-target-tab:hover { color: #94a3b8; background: rgba(148, 163, 184, 0.06); }

.wb-target-tab--active {
  color: #a5b4fc;
  background: rgba(99, 102, 241, 0.12);
  border-color: rgba(99, 102, 241, 0.2);
}

.wb-target-name {
  font-size: 14px;
  font-weight: 700;
  color: #f1f5f9;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-dirty {
  font-size: 10px;
  color: #f59e0b;
  font-weight: 700;
}

.wb-target-id {
  font-size: 10px;
  color: #475569;
  font-variant-numeric: tabular-nums;
}

.wb-btn {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.15);
  color: #94a3b8;
  font-size: 11px;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.wb-btn:hover:not(:disabled) {
  background: rgba(148, 163, 184, 0.08);
  color: #e2e8f0;
}

.wb-btn--primary {
  background: rgba(99, 102, 241, 0.15);
  border-color: rgba(99, 102, 241, 0.3);
  color: #a5b4fc;
}

.wb-btn--primary:hover:not(:disabled) {
  background: rgba(99, 102, 241, 0.25);
}

.wb-btn--publish {
  background: rgba(16, 185, 129, 0.1);
  border-color: rgba(16, 185, 129, 0.25);
  color: #6ee7b7;
}

.wb-btn--publish:hover {
  background: rgba(16, 185, 129, 0.18);
}

.wb-btn:disabled { opacity: 0.35; cursor: not-allowed; }

.wb-save-msg {
  font-size: 11px;
  color: #f59e0b;
  font-weight: 600;
}

.wb-save-msg--ok { color: #6ee7b7; }

.wb-user {
  font-size: 11px;
  color: #64748b;
  padding: 0 4px;
  border-left: 1px solid rgba(148, 163, 184, 0.1);
  margin-left: 4px;
}

/* ── Body ── */
.wb-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.wb-body--canvas-focus {
  background: #080f1a;
}

.wb-col {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.wb-col--left {
  border-right: 1px solid rgba(148, 163, 184, 0.08);
}

.wb-col--center {
  flex: 1;
  min-width: 0;
}

.wb-col--right {
  border-left: 1px solid rgba(148, 163, 184, 0.08);
}

/* Resize handle */
.wb-resize {
  width: 4px;
  background: transparent;
  cursor: col-resize;
  flex-shrink: 0;
  transition: background 0.15s ease;
}

.wb-resize:hover { background: rgba(99, 102, 241, 0.3); }

/* Loading / error */
.wb-loading {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
  font-size: 13px;
}

.wb-loading-spinner {
  animation: spin 1.5s linear infinite;
  display: inline-block;
  color: #6366f1;
}

@keyframes spin {
  0% { opacity: 1; }
  33% { opacity: 0.3; }
  66% { opacity: 0.7; }
  100% { opacity: 1; }
}

.wb-error {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fca5a5;
  font-size: 13px;
}

/* ── Drawers ── */
.wb-drawer {
  position: fixed;
  bottom: 0;
  right: 0;
  width: 480px;
  max-height: 60vh;
  background: rgba(10, 18, 32, 0.98);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-bottom: none;
  border-radius: 14px 14px 0 0;
  box-shadow: 0 -8px 32px rgba(0, 0, 0, 0.5);
  z-index: 200;
  display: flex;
  flex-direction: column;
  backdrop-filter: blur(12px);
}

.wb-drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  font-size: 13px;
  font-weight: 700;
  color: #e2e8f0;
  flex-shrink: 0;
}

.wb-drawer-close {
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 5px;
  transition: color 0.15s ease;
}

.wb-drawer-close:hover { color: #e2e8f0; }

.wb-drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px;
}

.drawer-hint {
  font-size: 12px;
  color: #94a3b8;
  margin: 0 0 10px;
  line-height: 1.6;
}

.drawer-warn {
  font-size: 12px;
  color: #f59e0b;
  margin: 0;
  padding: 8px 10px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.15);
  border-radius: 8px;
}

.drawer-json {
  font-size: 10px;
  color: #94a3b8;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 8px;
  padding: 10px;
  overflow: auto;
  max-height: 300px;
  white-space: pre-wrap;
  word-break: break-all;
}

/* Drawer transition */
.drawer-enter-active, .drawer-leave-active {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s ease;
}

.drawer-enter-from, .drawer-leave-to {
  transform: translateY(100%);
  opacity: 0;
}

html[data-workbench-theme='light'] .wb-shell { background: #f5f5f7; color: #1d1d1f; }
html[data-workbench-theme='light'] .wb-shell--embedded { border-color: rgba(0,0,0,0.08); background: #ffffff; }
html[data-workbench-theme='light'] .wb-topbar { background: rgba(255,255,255,0.98); border-bottom-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .wb-logo { color: #0071e3; }
html[data-workbench-theme='light'] .wb-logo-return { color: rgba(0,0,0,0.35); }
html[data-workbench-theme='light'] .wb-logo-home-link:hover .wb-logo-return { color: #0071e3; }
html[data-workbench-theme='light'] .wb-logo-home-link:hover { color: #005bb5; }
html[data-workbench-theme='light'] .wb-logo-badge { background: rgba(0,113,227,0.08); color: #0071e3; border-color: rgba(0,113,227,0.15); }
html[data-workbench-theme='light'] .wb-target-tab { color: #86868b; }
html[data-workbench-theme='light'] .wb-target-tab:hover { color: #1d1d1f; background: rgba(0,0,0,0.04); }
html[data-workbench-theme='light'] .wb-target-tab--active { color: #0071e3; background: rgba(0,113,227,0.08); border-color: rgba(0,113,227,0.15); }
html[data-workbench-theme='light'] .wb-target-name { color: #1d1d1f; }
html[data-workbench-theme='light'] .wb-dirty { color: #b45309; }
html[data-workbench-theme='light'] .wb-target-id { color: #86868b; }
html[data-workbench-theme='light'] .wb-btn { background: rgba(0,0,0,0.03); border-color: rgba(0,0,0,0.1); color: #1d1d1f; }
html[data-workbench-theme='light'] .wb-btn:hover:not(:disabled) { background: rgba(0,0,0,0.06); color: #1d1d1f; }
html[data-workbench-theme='light'] .wb-btn--primary { background: #0071e3; border-color: #0071e3; color: #ffffff; }
html[data-workbench-theme='light'] .wb-btn--primary:hover:not(:disabled) { background: #005bb5; }
html[data-workbench-theme='light'] .wb-btn--publish { background: rgba(34,197,94,0.08); border-color: rgba(34,197,94,0.2); color: #16a34a; }
html[data-workbench-theme='light'] .wb-btn--publish:hover { background: rgba(34,197,94,0.15); }
html[data-workbench-theme='light'] .wb-save-msg { color: #b45309; }
html[data-workbench-theme='light'] .wb-save-msg--ok { color: #16a34a; }
html[data-workbench-theme='light'] .wb-user { color: #86868b; border-left-color: rgba(0,0,0,0.08); }
html[data-workbench-theme='light'] .wb-body--canvas-focus { background: #f5f5f7; }
html[data-workbench-theme='light'] .wb-col--left { border-right-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .wb-col--right { border-left-color: rgba(0,0,0,0.06); }
html[data-workbench-theme='light'] .wb-resize:hover { background: rgba(0,113,227,0.2); }
html[data-workbench-theme='light'] .wb-loading { color: #86868b; }
html[data-workbench-theme='light'] .wb-loading-spinner { color: #0071e3; }
html[data-workbench-theme='light'] .wb-error { color: #dc2626; }
html[data-workbench-theme='light'] .wb-drawer { background: rgba(255,255,255,0.98); border-color: rgba(0,0,0,0.08); box-shadow: 0 -8px 32px rgba(0,0,0,0.1); }
html[data-workbench-theme='light'] .wb-drawer-header { border-bottom-color: rgba(0,0,0,0.06); color: #1d1d1f; }
html[data-workbench-theme='light'] .wb-drawer-close { color: #86868b; }
html[data-workbench-theme='light'] .wb-drawer-close:hover { color: #1d1d1f; }
html[data-workbench-theme='light'] .drawer-hint { color: #86868b; }
html[data-workbench-theme='light'] .drawer-warn { color: #b45309; background: rgba(245,158,11,0.06); border-color: rgba(245,158,11,0.15); }
html[data-workbench-theme='light'] .drawer-json { color: #515154; background: rgba(0,0,0,0.03); border-color: rgba(0,0,0,0.08); }

/* ── Mobile adaptation ── */
@media (max-width: 768px) {
  .wb-topbar {
    height: auto;
    min-height: 44px;
    flex-wrap: wrap;
    gap: 6px;
    padding: 6px 10px;
  }
  .wb-topbar-left { gap: 4px; flex-wrap: wrap; }
  .wb-topbar-center { order: -1; width: 100%; justify-content: flex-start; padding: 2px 0; }
  .wb-target-name { font-size: 13px; max-width: 180px; }
  .wb-topbar-right { gap: 4px; flex-wrap: wrap; }
  .wb-btn { padding: 4px 8px; font-size: 10px; }
  .wb-target-tabs { gap: 1px; }
  .wb-target-tab { padding: 3px 6px; font-size: 10px; }
  .wb-logo { font-size: 12px; }
  .wb-logo-badge { font-size: 8px; padding: 1px 4px; }
  .wb-user { display: none; }
  .wb-body--mobile { flex-direction: column; }
  .wb-body--mobile .wb-col { width: 100% !important; flex: 1; min-height: 0; }
  .wb-body--mobile .wb-col--left,
  .wb-body--mobile .wb-col--right { border: none; }
  .wb-drawer { width: 100%; border-radius: 14px 14px 0 0; }
  .wb-shell { padding-bottom: 56px; }
}

.wb-mobile-tabbar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-around;
  background: rgba(8, 15, 26, 0.96);
  border-top: 1px solid rgba(148, 163, 184, 0.1);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  z-index: 9000;
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

html[data-workbench-theme='light'] .wb-mobile-tabbar {
  background: rgba(255, 255, 255, 0.96);
  border-top-color: rgba(0, 0, 0, 0.08);
}

.wb-mobile-tab {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 4px 12px;
  border: none;
  background: transparent;
  color: #64748b;
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.15s ease;
}

html[data-workbench-theme='light'] .wb-mobile-tab { color: #86868b; }

.wb-mobile-tab--active { color: #a5b4fc; }
html[data-workbench-theme='light'] .wb-mobile-tab--active { color: #0071e3; }
</style>
