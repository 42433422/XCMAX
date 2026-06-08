<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { useWorkbenchStore } from '../../../stores/workbench'
import { useAgentLoop } from '../../../composables/useAgentLoop'
import { useAuthStore } from '../../../stores/auth'
import { api } from '../../../api'
import { isPlannedDutyRosterPkgId as isDutyRosterEmployee } from '../../../utils/workbenchEmployeeFilter'
import type { AgentRun } from '../../../stores/workbench'
import EmployeeAiDraftReview from '../../../components/workbench/EmployeeAiDraftReview.vue'

const store = useWorkbenchStore()
const agentLoop = useAgentLoop()
const route = useRoute()

const auth = useAuthStore()
const { isAdmin } = storeToRefs(auth)

// ── View toggle ────────────────────────────────────────────────────────────
type RailView = 'list' | 'agent'
const view = ref<RailView>('list')

// ── Employee list ──────────────────────────────────────────────────────────
const HIDDEN_PKG_IDS_KEY = 'modstore_emp_chat_hidden_pkg_ids'

function readHiddenPkgIds(): Set<string> {
  try {
    const raw = localStorage.getItem(HIDDEN_PKG_IDS_KEY)
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.filter((x): x is string => typeof x === 'string'))
  } catch {
    return new Set()
  }
}

type EmployeeRow = { id: string; name?: string; source?: 'catalog' | 'v1_catalog' }

const employees = ref<EmployeeRow[]>([])
const hiddenPkgIds = ref<Set<string>>(readHiddenPkgIds())
const loadingList = ref(false)
const listError = ref('')
const deletingId = ref('')
const purgeBusy = ref(false)

/** 仅显示未隐藏的非在岗员工；在岗员工不可操作，不在此列表 */
const visibleEmployees = computed(() =>
  employees.value.filter((e) => !hiddenPkgIds.value.has(e.id) && !isDutyRosterEmployee(e.id)),
)
const hasV1OnlyEmployees = computed(() => employees.value.some((e) => e.source === 'v1_catalog'))

function persistHiddenPkgIds() {
  localStorage.setItem(HIDDEN_PKG_IDS_KEY, JSON.stringify([...hiddenPkgIds.value]))
}

function hideLocally(pkgId: string) {
  hiddenPkgIds.value = new Set([...hiddenPkgIds.value, pkgId])
  persistHiddenPkgIds()
}

function clearHiddenPkgIds() {
  hiddenPkgIds.value = new Set()
  persistHiddenPkgIds()
}

async function loadEmployees() {
  listError.value = ''
  loadingList.value = true
  try {
    const rows = await api.listEmployees()
    if (!Array.isArray(rows)) {
      employees.value = []
      return
    }
    employees.value = (rows as Record<string, unknown>[]).map((e) => {
      const id = String(e.id ?? '').trim()
      const rawSrc = e.source
      const source: EmployeeRow['source'] = rawSrc === 'v1_catalog' ? 'v1_catalog' : 'catalog'
      return { id, name: typeof e.name === 'string' ? e.name : undefined, source }
    })
  } catch (e: unknown) {
    listError.value = e instanceof Error ? e.message : String(e)
    employees.value = []
  } finally {
    loadingList.value = false
  }
}

async function confirmDeleteEmployee(e: EmployeeRow) {
  if (!isAdmin.value) return
  if (isDutyRosterEmployee(e.id)) {
    window.alert('该员工属于编制在岗岗位包（与「员工工作流管理」矩阵一致），已锁定，禁止从工作台删除。')
    return
  }
  const label = e.name || e.id
  const ok = window.confirm(`确定删除员工包「${label}」（${e.id}）？将从目录与数据库移除，不可恢复。`)
  if (!ok) return
  deletingId.value = e.id
  listError.value = ''
  try {
    await api.adminDeleteEmployeePack(e.id)
    hiddenPkgIds.value.delete(e.id)
    persistHiddenPkgIds()
    await loadEmployees()
  } catch (err: unknown) {
    listError.value = err instanceof Error ? err.message : String(err)
  } finally {
    deletingId.value = ''
  }
}

async function purgeAllEmployees() {
  if (!isAdmin.value || purgeBusy.value) return
  const ok = window.confirm(
    '确定一键清空员工仓库？\n将原子地删除 packages.json 与 catalog_items 中所有 employee_pack 行（含磁盘 .xcemp 文件），\n用于解决「老是删不完」（两个数据源 pkg_id 不重合时单条对账会遗漏）。\n不可恢复。',
  )
  if (!ok) return
  purgeBusy.value = true
  listError.value = ''
  try {
    const res: any = await api.adminPurgeAllEmployeePacks()
    const a = Number(res?.removed_packages_json || 0)
    const b = Number(res?.removed_db_rows || 0)
    const c = Number(res?.removed_files || 0)
    hiddenPkgIds.value = new Set()
    persistHiddenPkgIds()
    await loadEmployees()
    listError.value = `已清空员工仓库：packages.json 删 ${a} 行，DB 删 ${b} 行，磁盘文件删 ${c} 个`
  } catch (err: unknown) {
    listError.value = err instanceof Error ? err.message : String(err)
  } finally {
    purgeBusy.value = false
  }
}

// ── Emit to parent (WorkbenchShell) ───────────────────────────────────────
const emit = defineEmits<{
  (e: 'select-employee', id: string): void
}>()

function selectEmployee(id: string) {
  emit('select-employee', id)
}

// ── Agent triggers ─────────────────────────────────────────────────────────

const agentInput = ref('')
const agentRunning = ref(false)
let currentAbort: (() => void) | null = null

async function runAgentDraft() {
  const brief = agentInput.value.trim()
  if (!brief || agentRunning.value) return
  agentRunning.value = true
  agentInput.value = ''
  view.value = 'agent'

  const { abort } = await agentLoop.runEmployeeDraft(brief)
  currentAbort = abort
  agentRunning.value = false
}

async function retryEmployeeDraft() {
  const brief = store.currentRun?.brief?.trim()
  if (!brief || agentRunning.value) return
  agentRunning.value = true
  const { abort } = await agentLoop.runEmployeeDraft(brief)
  currentAbort = abort
  agentRunning.value = false
}

async function onDraftPublished(_modId: string) {
  await loadEmployees()
}

function abortCurrentRun() {
  currentAbort?.()
  currentAbort = null
  agentRunning.value = false
}

function applyRunManifest(run: AgentRun) {
  if (!run.manifest) return
  store.setTarget(store.target.kind, store.target.id, run.manifest as Record<string, unknown>, store.target.name)
}

function formatTs(ts: number) {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const AGENT_SUGGESTED = [
  '帮我创建一个电话客服员工，专注售后问题处理',
  '创建一个数据分析员工，能处理 CSV 并生成报表',
  '设计一个全能型 AI 助手，支持图文理解和对话',
]

function useSuggestion(s: string) {
  agentInput.value = s
}

async function maybeSelectFromRoute() {
  const packId = String(route.query.packId ?? route.query.id ?? '').trim()
  if (packId) {
    selectEmployee(packId)
  }
}

onMounted(async () => {
  await loadEmployees()
  await maybeSelectFromRoute()
})

watch(
  () => String(route.query.packId ?? route.query.id ?? '').trim(),
  async (packId, prev) => {
    if (!packId || packId === prev) return
    await loadEmployees()
    await maybeSelectFromRoute()
  },
)
</script>

<template>
  <div class="left-rail">
    <!-- Tab bar -->
    <div class="lr-tabs">
      <button class="lr-tab" :class="{ 'lr-tab--active': view === 'list' }" @click="view = 'list'">
        <span class="lr-tab-icon"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"><rect x="3" y="4" width="10" height="7" rx="1.5"/><circle cx="6" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><circle cx="10" cy="7.5" r="0.75" fill="currentColor" stroke="none"/><path d="M6 11v1.5M10 11v1.5M5 4V2.5M11 4V2.5"/></svg></span> 员工列表
      </button>
      <button class="lr-tab" :class="{ 'lr-tab--active': view === 'agent' }" @click="view = 'agent'">
        <span class="lr-tab-icon">⚡</span> Agent
        <span v-if="store.agentRuns.length" class="lr-tab-badge">{{ store.agentRuns.length }}</span>
      </button>
    </div>

    <!-- ── Employee list panel ─────────────────────────────────────── -->
    <div v-if="view === 'list'" class="lr-pane list-pane">
      <!-- Toolbar -->
      <div class="list-toolbar">
        <button type="button" class="list-btn list-btn--ghost" :disabled="loadingList" @click="loadEmployees">
          {{ loadingList ? '加载中…' : '刷新' }}
        </button>
        <button
          v-if="isAdmin"
          type="button"
          class="list-btn list-btn--danger"
          :disabled="purgeBusy"
          title="原子地清空 packages.json 与 catalog_items 中所有 employee_pack"
          @click="purgeAllEmployees"
        >
          {{ purgeBusy ? '清空中…' : '一键清空' }}
        </button>
      </div>

      <p v-if="listError" class="list-error">{{ listError }}</p>

      <!-- Empty states -->
      <p v-if="!employees.length && !loadingList && !listError" class="list-empty">
        暂无员工包
      </p>
      <p v-else-if="!visibleEmployees.length && !loadingList" class="list-empty">
        列表中的员工均已隐藏。
        <button type="button" class="list-btn--inline" @click="clearHiddenPkgIds">显示全部</button>
      </p>

      <!-- Employee rows -->
      <ul v-else class="emp-list">
        <li v-for="e in visibleEmployees" :key="e.id" class="emp-row">
          <button
            type="button"
            class="emp-row__btn"
            :class="{ 'emp-row__btn--active': store.target.id === e.id }"
            @click="selectEmployee(e.id)"
          >
            <span class="emp-row__name-row">
              <span class="emp-row__name">{{ e.name || e.id }}</span>
              <span v-if="isDutyRosterEmployee(e.id)" class="emp-badge emp-badge--duty" title="编制内岗位，与「MODstore 在岗」矩阵一致">在岗</span>
            </span>
            <span class="emp-row__id">{{ e.id }}{{ e.source === 'v1_catalog' ? ' · 仅目录' : '' }}</span>
          </button>
          <div class="emp-row__actions">
            <button
              v-if="isAdmin"
              type="button"
              class="emp-action emp-action--danger"
              :disabled="deletingId === e.id || isDutyRosterEmployee(e.id)"
              :title="isDutyRosterEmployee(e.id) ? '编制在岗员工包已锁定' : '从服务端删除该员工包'"
              @click.stop="confirmDeleteEmployee(e)"
            >
              {{ deletingId === e.id ? '…' : '删' }}
            </button>
            <button
              v-else
              type="button"
              class="emp-action"
              title="仅从本机列表隐藏"
              @click.stop="hideLocally(e.id)"
            >
              隐
            </button>
          </div>
        </li>
      </ul>
    </div>

    <!-- ── Agent panel ────────────────────────────────────────────────── -->
    <div v-else class="lr-pane agent-pane">
      <!-- Agent input -->
      <div class="agent-input-area">
        <textarea
          v-model="agentInput"
          class="agent-input"
          placeholder="用一句话描述你想创建的员工，AI 将自动生成完整配置…"
          rows="3"
          :disabled="agentRunning"
        />
        <div class="agent-input-actions">
          <button
            v-if="!agentRunning"
            class="agent-run-btn"
            :disabled="!agentInput.trim()"
            @click="runAgentDraft"
          >
            ▶ 生成员工
          </button>
          <button v-else class="agent-abort-btn" @click="abortCurrentRun">
            ◼ 停止
          </button>
        </div>
        <div class="agent-suggestions">
          <button v-for="s in AGENT_SUGGESTED" :key="s" class="agent-suggestion" @click="useSuggestion(s)">
            {{ s }}
          </button>
        </div>
      </div>

      <EmployeeAiDraftReview
        embedded
        class="lr-draft-review"
        @retry="retryEmployeeDraft"
        @published="onDraftPublished"
      />

      <!-- Runs timeline -->
      <div class="agent-runs">
        <div v-if="!store.agentRuns.length" class="agent-empty">
          还没有 Agent 运行记录。填写描述后点击「生成员工」开始。
        </div>

        <div v-for="run in store.agentRuns" :key="run.id" class="agent-run">
          <div class="agent-run__header">
            <span class="agent-run__brief">{{ run.brief }}</span>
            <span class="agent-run__ts">{{ formatTs(run.startedAt) }}</span>
            <span class="agent-run__status" :class="`agent-run__status--${run.status}`">
              {{ run.status === 'running' ? '运行中' : run.status === 'done' ? '完成' : run.status === 'error' ? '失败' : '空闲' }}
            </span>
          </div>

          <!-- Events timeline -->
          <div class="agent-run__events">
            <div
              v-for="ev in run.events"
              :key="ev.id"
              class="agent-event"
              :class="`agent-event--${ev.status}`"
            >
              <span class="agent-event__dot"></span>
              <div class="agent-event__body">
                <span class="agent-event__label">{{ ev.label }}</span>
                <span v-if="ev.status === 'running'" class="agent-event__pulse">●</span>
                <span v-else-if="ev.status === 'done'" class="agent-event__check">✓</span>
                <span v-else-if="ev.status === 'error'" class="agent-event__err">✕</span>
              </div>
            </div>
          </div>

          <!-- Apply to canvas button -->
          <div v-if="run.manifest && run.status === 'done'" class="agent-run__apply">
            <button class="agent-apply-btn" @click="applyRunManifest(run)">
              ↗ 应用到画布
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.left-rail {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: rgba(8, 15, 26, 0.98);
}

/* Tabs */
.lr-tabs {
  display: flex;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
  flex-shrink: 0;
}

.lr-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 10px 8px;
  background: transparent;
  border: none;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
  position: relative;
}

.lr-tab:hover { color: #94a3b8; }

.lr-tab--active {
  color: #a5b4fc;
  border-bottom: 2px solid #6366f1;
}

.lr-tab-icon { font-size: 13px; }

.lr-tab-badge {
  background: #6366f1;
  color: #fff;
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 999px;
  min-width: 16px;
  text-align: center;
}

/* Pane */
.lr-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Employee list ── */
.list-pane {
  overflow-y: auto;
  padding: 8px;
  gap: 6px;
  scrollbar-width: thin;
  scrollbar-color: rgba(99, 102, 241, 0.3) transparent;
}

.list-toolbar {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
  margin-bottom: 6px;
}

.list-btn {
  padding: 4px 10px;
  border-radius: 7px;
  border: none;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s ease;
}

.list-btn--ghost {
  background: rgba(255, 255, 255, 0.07);
  color: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.list-btn--ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
}

.list-btn--ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.list-btn--danger {
  background: rgba(239, 68, 68, 0.1);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.list-btn--danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.18);
}

.list-btn--danger:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.list-btn--inline {
  background: none;
  border: none;
  color: #a5b4fc;
  font-size: 11px;
  cursor: pointer;
  text-decoration: underline;
  padding: 0;
}

.list-hint {
  font-size: 10px;
  color: #64748b;
  line-height: 1.4;
  margin: 0 0 4px;
}

.list-hint--warn {
  color: #f59e0b;
}

.list-error {
  font-size: 11px;
  color: #f87171;
  margin: 0 0 4px;
}

.list-empty {
  font-size: 11px;
  color: #475569;
  padding: 16px 8px;
  text-align: center;
  line-height: 1.5;
}

.emp-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.emp-row {
  display: flex;
  align-items: stretch;
  gap: 4px;
  min-width: 0;
}

.emp-row__btn {
  flex: 1 1 auto;
  min-width: 0;
  text-align: left;
  padding: 7px 9px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.25);
  color: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
}

.emp-row__btn:hover {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.3);
}

.emp-row__btn--active {
  border-color: rgba(99, 102, 241, 0.6);
  background: rgba(99, 102, 241, 0.14);
}

.emp-row__name {
  font-size: 12px;
  font-weight: 600;
  color: #e2e8f0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.emp-row__name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.emp-badge {
  flex-shrink: 0;
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 4px;
  letter-spacing: 0.02em;
}

.emp-badge--duty {
  background: rgba(16, 185, 129, 0.2);
  color: #6ee7b7;
  border: 1px solid rgba(16, 185, 129, 0.35);
}

.emp-row__id {
  display: block;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.4);
  word-break: break-all;
  margin-top: 1px;
}

.emp-row__actions {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}

.emp-action {
  flex: 0 0 auto;
  padding: 3px 6px;
  font-size: 10px;
  line-height: 1.2;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.12s ease;
}

.emp-action:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
}

.emp-action:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.emp-action--danger {
  border-color: rgba(248, 113, 113, 0.3);
  color: #fca5a5;
}

.emp-action--danger:hover:not(:disabled) {
  background: rgba(248, 113, 113, 0.12);
}

/* ── Agent ── */
.agent-pane {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  gap: 0;
  min-height: 0;
}

.lr-draft-review {
  flex: 1;
  min-height: 120px;
  min-width: 0;
}

.agent-input-area {
  padding: 12px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.08);
  flex-shrink: 0;
}

.agent-input {
  width: 100%;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.12);
  border-radius: 10px;
  color: #e2e8f0;
  font-size: 13px;
  padding: 9px 11px;
  resize: none;
  outline: none;
  font-family: inherit;
  line-height: 1.5;
  box-sizing: border-box;
}

.agent-input:focus { border-color: rgba(99, 102, 241, 0.4); }

.agent-input-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
  gap: 6px;
}

.agent-run-btn {
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border: none;
  border-radius: 9px;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  padding: 7px 16px;
  cursor: pointer;
  transition: all 0.15s ease;
  letter-spacing: 0.02em;
}

.agent-run-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #818cf8, #a78bfa);
  transform: translateY(-1px);
}

.agent-run-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.agent-abort-btn {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 9px;
  color: #f87171;
  font-size: 12px;
  font-weight: 700;
  padding: 7px 16px;
  cursor: pointer;
  animation: pulse-red 1s ease infinite;
}

@keyframes pulse-red {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.65; }
}

.agent-suggestions {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
}

.agent-suggestion {
  background: rgba(99, 102, 241, 0.06);
  border: 1px solid rgba(99, 102, 241, 0.15);
  color: #64748b;
  font-size: 10px;
  padding: 5px 9px;
  border-radius: 7px;
  cursor: pointer;
  text-align: left;
  transition: all 0.12s ease;
}

.agent-suggestion:hover {
  background: rgba(99, 102, 241, 0.12);
  color: #94a3b8;
}

.agent-runs {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  scrollbar-width: thin;
  scrollbar-color: rgba(99, 102, 241, 0.3) transparent;
}

.agent-empty {
  color: #475569;
  font-size: 12px;
  text-align: center;
  margin: auto;
  padding: 20px;
  line-height: 1.6;
}

.agent-run {
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(148, 163, 184, 0.1);
  border-radius: 12px;
  padding: 10px 12px;
}

.agent-run__header {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.agent-run__brief {
  flex: 1;
  font-size: 12px;
  color: #e2e8f0;
  font-weight: 500;
  line-height: 1.4;
  min-width: 0;
  word-break: break-word;
}

.agent-run__ts {
  font-size: 9px;
  color: #475569;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.agent-run__status {
  font-size: 9px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 999px;
  flex-shrink: 0;
}

.agent-run__status--running {
  background: rgba(99, 102, 241, 0.15);
  color: #a5b4fc;
  border: 1px solid rgba(99, 102, 241, 0.25);
  animation: pulse-blue 1.2s ease infinite;
}

@keyframes pulse-blue {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.agent-run__status--done {
  background: rgba(16, 185, 129, 0.12);
  color: #6ee7b7;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.agent-run__status--error {
  background: rgba(239, 68, 68, 0.12);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.agent-run__events {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-left: 4px;
  border-left: 1px solid rgba(148, 163, 184, 0.1);
  padding-left: 10px;
}

.agent-event {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 2px 0;
}

.agent-event__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-left: -13px;
  background: rgba(100, 116, 139, 0.4);
}

.agent-event--running .agent-event__dot { background: #6366f1; animation: pulse-blue 0.8s ease infinite; }
.agent-event--done .agent-event__dot { background: #10b981; }
.agent-event--error .agent-event__dot { background: #ef4444; }

.agent-event__body {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 1;
}

.agent-event__label {
  font-size: 11px;
  color: #94a3b8;
  flex: 1;
}

.agent-event--running .agent-event__label { color: #c7d2fe; }
.agent-event--done .agent-event__label { color: #6ee7b7; }
.agent-event--error .agent-event__label { color: #fca5a5; }

.agent-event__pulse {
  color: #6366f1;
  font-size: 8px;
  animation: pulse-blue 0.6s ease infinite;
}

.agent-event__check { color: #10b981; font-size: 11px; font-weight: 700; }
.agent-event__err { color: #ef4444; font-size: 11px; font-weight: 700; }

.agent-run__apply {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(148, 163, 184, 0.08);
}

.agent-apply-btn {
  width: 100%;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
  color: #6ee7b7;
  font-size: 12px;
  font-weight: 700;
  padding: 7px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.agent-apply-btn:hover {
  background: rgba(16, 185, 129, 0.18);
  border-color: rgba(16, 185, 129, 0.4);
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Light theme overrides
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
html[data-workbench-theme='light'] .left-rail {
  background: #f5f5f7;
}
html[data-workbench-theme='light'] .lr-tabs {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .lr-tab {
  color: #86868b;
}
html[data-workbench-theme='light'] .lr-tab:hover {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .lr-tab--active {
  color: #0071e3;
  border-bottom-color: #0071e3;
}
html[data-workbench-theme='light'] .lr-tab-badge {
  background: #0071e3;
}
html[data-workbench-theme='light'] .list-pane {
  scrollbar-color: rgba(0, 113, 227, 0.2) transparent;
}
html[data-workbench-theme='light'] .list-btn--ghost {
  background: rgba(0, 0, 0, 0.04);
  color: #1d1d1f;
  border-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .list-btn--ghost:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.07);
}
html[data-workbench-theme='light'] .list-btn--danger {
  background: rgba(220, 38, 38, 0.06);
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.18);
}
html[data-workbench-theme='light'] .list-btn--danger:hover:not(:disabled) {
  background: rgba(220, 38, 38, 0.1);
}
html[data-workbench-theme='light'] .list-btn--inline {
  color: #0071e3;
}
html[data-workbench-theme='light'] .list-hint {
  color: #86868b;
}
html[data-workbench-theme='light'] .list-error {
  color: #dc2626;
}
html[data-workbench-theme='light'] .list-empty {
  color: #86868b;
}
html[data-workbench-theme='light'] .emp-row__btn {
  border-color: rgba(0, 0, 0, 0.08);
  background: #ffffff;
}
html[data-workbench-theme='light'] .emp-row__btn:hover {
  background: rgba(0, 113, 227, 0.05);
  border-color: rgba(0, 113, 227, 0.2);
}
html[data-workbench-theme='light'] .emp-row__btn--active {
  border-color: rgba(0, 113, 227, 0.35);
  background: rgba(0, 113, 227, 0.07);
}
html[data-workbench-theme='light'] .emp-row__name {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .emp-badge--duty {
  background: rgba(16, 185, 129, 0.1);
  color: #059669;
  border-color: rgba(16, 185, 129, 0.2);
}
html[data-workbench-theme='light'] .emp-row__id {
  color: #86868b;
}
html[data-workbench-theme='light'] .emp-action {
  border-color: rgba(0, 0, 0, 0.08);
  background: rgba(0, 0, 0, 0.03);
  color: #86868b;
}
html[data-workbench-theme='light'] .emp-action:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .emp-action--danger {
  border-color: rgba(220, 38, 38, 0.18);
  color: #dc2626;
}
html[data-workbench-theme='light'] .emp-action--danger:hover:not(:disabled) {
  background: rgba(220, 38, 38, 0.08);
}
html[data-workbench-theme='light'] .agent-input-area {
  border-bottom-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .agent-input {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.1);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .agent-input:focus {
  border-color: rgba(0, 113, 227, 0.4);
}
html[data-workbench-theme='light'] .agent-run-btn {
  background: #0071e3;
}
html[data-workbench-theme='light'] .agent-run-btn:hover:not(:disabled) {
  background: #0060c7;
}
html[data-workbench-theme='light'] .agent-abort-btn {
  background: rgba(220, 38, 38, 0.07);
  border-color: rgba(220, 38, 38, 0.2);
  color: #dc2626;
}
html[data-workbench-theme='light'] .agent-suggestion {
  background: rgba(0, 113, 227, 0.04);
  border-color: rgba(0, 113, 227, 0.12);
  color: #86868b;
}
html[data-workbench-theme='light'] .agent-suggestion:hover {
  background: rgba(0, 113, 227, 0.08);
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .agent-runs {
  scrollbar-color: rgba(0, 113, 227, 0.2) transparent;
}
html[data-workbench-theme='light'] .agent-empty {
  color: #86868b;
}
html[data-workbench-theme='light'] .agent-run {
  background: #ffffff;
  border-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .agent-run__brief {
  color: #1d1d1f;
}
html[data-workbench-theme='light'] .agent-run__ts {
  color: #86868b;
}
html[data-workbench-theme='light'] .agent-run__status--running {
  background: rgba(0, 113, 227, 0.07);
  color: #0071e3;
  border-color: rgba(0, 113, 227, 0.18);
}
html[data-workbench-theme='light'] .agent-run__status--done {
  background: rgba(16, 185, 129, 0.07);
  color: #059669;
  border-color: rgba(16, 185, 129, 0.15);
}
html[data-workbench-theme='light'] .agent-run__status--error {
  background: rgba(220, 38, 38, 0.07);
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.15);
}
html[data-workbench-theme='light'] .agent-run__events {
  border-left-color: rgba(0, 0, 0, 0.08);
}
html[data-workbench-theme='light'] .agent-event__dot {
  background: rgba(0, 0, 0, 0.12);
}
html[data-workbench-theme='light'] .agent-event--running .agent-event__dot {
  background: #0071e3;
}
html[data-workbench-theme='light'] .agent-event__label {
  color: #86868b;
}
html[data-workbench-theme='light'] .agent-event--running .agent-event__label {
  color: #0071e3;
}
html[data-workbench-theme='light'] .agent-event--done .agent-event__label {
  color: #059669;
}
html[data-workbench-theme='light'] .agent-event--error .agent-event__label {
  color: #dc2626;
}
html[data-workbench-theme='light'] .agent-event__pulse {
  color: #0071e3;
}
html[data-workbench-theme='light'] .agent-event__check {
  color: #059669;
}
html[data-workbench-theme='light'] .agent-event__err {
  color: #dc2626;
}
html[data-workbench-theme='light'] .agent-run__apply {
  border-top-color: rgba(0, 0, 0, 0.06);
}
html[data-workbench-theme='light'] .agent-apply-btn {
  background: rgba(16, 185, 129, 0.07);
  border-color: rgba(16, 185, 129, 0.18);
  color: #059669;
}
html[data-workbench-theme='light'] .agent-apply-btn:hover {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.28);
}
</style>
