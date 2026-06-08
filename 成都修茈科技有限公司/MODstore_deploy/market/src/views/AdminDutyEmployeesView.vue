<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'
import AdminDutyEmployeeGraph from '../components/admin/AdminDutyEmployeeGraph.vue'
import { desktopOpsDeepLink } from '../utils/opsDeepLinks'

const route = useRoute()
const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

const alignBusy = ref(false)
const alignMsg = ref('')

async function runAlignLlm(dryRun: boolean) {
  if (alignBusy.value) return
  alignBusy.value = true
  alignMsg.value = ''
  try {
    const r = (await api.adminAlignEmployeeLlmToAuto(dryRun)) as Record<string, unknown>
    const u = Number(r.updated_count ?? 0)
    const s = Number(r.skipped_count ?? 0)
    const e = Number(r.error_count ?? 0)
    alignMsg.value = dryRun
      ? `预览：将改写 ${u} 个包（跳过 ${s}，不可用 ${e}）`
      : `已完成：改写 ${u} 个，跳过 ${s}，失败 ${e}。请刷新本页或值班图。`
  } catch (err: unknown) {
    alignMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    alignBusy.value = false
  }
}

interface HealthSummary {
  staffing?: {
    planned_count?: number
    registered_count?: number
    missing_employees?: string[]
    extra_employees?: string[]
    areas?: { key: string; label: string; missing: string[] }[]
  }
  employee_cron_jobs?: { employee_id: string; next_run_time: string | null }[]
  change_requests?: { pending?: number; failed?: number }
  incident_unknown_24h?: number
  env_flags?: Record<string, string>
}

const health = ref<HealthSummary>({})
const healthBusy = ref(false)
const healthErr = ref('')

async function loadHealth() {
  healthBusy.value = true
  healthErr.value = ''
  try {
    health.value = (await api.adminDutyGraphHealth()) as HealthSummary
  } catch (err: unknown) {
    healthErr.value = err instanceof Error ? err.message : String(err)
  } finally {
    healthBusy.value = false
  }
}

const missingCount = computed(() => health.value.staffing?.missing_employees?.length ?? 0)
const cronCount = computed(() => health.value.employee_cron_jobs?.length ?? 0)
const pendingCr = computed(() => health.value.change_requests?.pending ?? 0)
const failedCr = computed(() => health.value.change_requests?.failed ?? 0)
const unknownEvents = computed(() => health.value.incident_unknown_24h ?? 0)

const desktopDutyUrl = computed(() => {
  const raw = route.query.employee
  const employeeId = typeof raw === 'string'
    ? raw.trim()
    : Array.isArray(raw)
      ? String(raw[0] || '').trim()
      : ''
  return desktopOpsDeepLink(employeeId || undefined)
})

const dispatchOpen = ref(false)
const dispatchTask = ref('')
const dispatchAllowHighRisk = ref(false)
const dispatchBusy = ref(false)
const dispatchMsg = ref('')

async function submitDispatch() {
  if (!dispatchTask.value.trim() || dispatchBusy.value) return
  dispatchBusy.value = true
  dispatchMsg.value = ''
  try {
    const r = (await api.opsOrchestrateAsync({
      task_description: dispatchTask.value.trim(),
      use_task_router: true,
      max_concurrency: 3,
      allow_high_risk_real_run: dispatchAllowHighRisk.value,
      dispatch_source: 'web',
    })) as { ok?: boolean; job_id?: string }
    dispatchMsg.value = r.ok ? `已派发，job_id=${r.job_id}` : '派发失败'
    if (r.ok) {
      dispatchTask.value = ''
      dispatchOpen.value = false
    }
  } catch (err: unknown) {
    dispatchMsg.value = err instanceof Error ? err.message : String(err)
  } finally {
    dispatchBusy.value = false
  }
}

const moreOpen = ref(false)
const moreRoot = ref<HTMLElement | null>(null)
const graphRef = ref<InstanceType<typeof AdminDutyEmployeeGraph> | null>(null)

function openMissingGapPanel() {
  graphRef.value?.openGapPanel?.()
}

function toggleMore() {
  moreOpen.value = !moreOpen.value
}

function onDocClick(e: MouseEvent) {
  if (!moreOpen.value) return
  const root = moreRoot.value
  if (root && e.target instanceof Node && !root.contains(e.target)) {
    moreOpen.value = false
  }
}

onMounted(() => {
  if (isAdmin.value) loadHealth()
  document.addEventListener('mousedown', onDocClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocClick)
})
</script>

<template>
  <div v-if="!isAdmin" class="admin-duty-denied">
    <p>需要管理员权限才能访问此页面</p>
    <router-link to="/" class="btn btn-primary">返回首页</router-link>
  </div>
  <div v-else class="admin-duty-employees-view">
    <div v-if="dispatchOpen" class="admin-duty-dispatch">
      <textarea
        v-model="dispatchTask"
        placeholder="用自然语言描述需要做什么；task_router 会拆给合适的员工，并通过 CR 提交建议。例如：'在门户站点 footer 加上备案号'"
        rows="3"
      />
      <div class="admin-duty-dispatch__row">
        <label>
          <input type="checkbox" v-model="dispatchAllowHighRisk" />
          允许高风险动作（shell_exec / vibe / 高风险路径写入）
        </label>
        <button
          type="button"
          class="adt-btn adt-btn--primary"
          :disabled="dispatchBusy || !dispatchTask.trim()"
          @click="submitDispatch"
        >派发</button>
        <button
          type="button"
          class="adt-btn"
          @click="dispatchOpen = false"
        >取消</button>
        <span v-if="dispatchMsg" class="adt-msg">{{ dispatchMsg }}</span>
      </div>
    </div>

    <AdminDutyEmployeeGraph ref="graphRef" variant="page" :open="true">
      <template #pageActions>
        <a
          class="adt-btn adt-btn--ghost"
          :href="desktopDutyUrl"
          title="在 XCAGI 桌面打开值班主控"
        >在桌面打开</a>
        <button
          type="button"
          class="adt-btn adt-btn--primary"
          @click="dispatchOpen = !dispatchOpen"
        >
          下达任务
        </button>

        <button
          type="button"
          class="adt-stat adt-stat--btn"
          :title="`已规划 ${health.staffing?.planned_count ?? 0} 个岗位，已上架 ${health.staffing?.registered_count ?? 0} 个；点击查看缺岗分析`"
          @click="openMissingGapPanel"
        >
          缺岗 <strong :class="{ 'stat-warn': missingCount > 0 }">{{ missingCount }}</strong>
        </button>
        <span class="adt-stat" title="manifest 声明 schedule 后已被 APScheduler 注册的员工数">
          定时 <strong :class="{ 'stat-warn': cronCount === 0 }">{{ cronCount }}</strong>
        </span>
        <router-link
          class="adt-stat adt-stat--link"
          :to="{ name: 'admin-change-requests' }"
          :title="`pending=${pendingCr}, failed=${failedCr}`"
        >
          待审 CR <strong :class="{ 'stat-warn': pendingCr > 0 }">{{ pendingCr }}</strong>
        </router-link>
        <span class="adt-stat" title="近 24 小时进入 incident_bus 但未在 EVENT_TYPES 注册的事件计数">
          未识别事件 <strong :class="{ 'stat-warn': unknownEvents > 0 }">{{ unknownEvents }}</strong>
        </span>

        <button
          type="button"
          class="adt-btn adt-btn--ghost"
          :disabled="healthBusy"
          title="重新拉取健康看板（缺岗 / 定时 / 待审 CR / 未识别事件）"
          @click="loadHealth"
        >{{ healthBusy ? '刷新中…' : '刷新看板' }}</button>

        <div ref="moreRoot" class="adt-more">
          <button
            type="button"
            class="adt-btn adt-btn--ghost"
            :class="{ 'adt-btn--active': moreOpen }"
            @click="toggleMore"
          >
            更多操作 <span class="adt-caret">▾</span>
          </button>
          <div v-if="moreOpen" class="adt-popover" role="menu">
            <p class="adt-popover__hint">
              仍为 DeepSeek 默认的员工包可一键改为「自动」（跟随账户可用密钥）并写回目录。
            </p>
            <div class="adt-popover__group">
              <span class="adt-popover__label">LLM 对齐</span>
              <button
                type="button"
                class="adt-btn adt-btn--block"
                :disabled="alignBusy"
                @click="runAlignLlm(true)"
              >预览对齐</button>
              <button
                type="button"
                class="adt-btn adt-btn--block adt-btn--primary"
                :disabled="alignBusy"
                @click="runAlignLlm(false)"
              >执行对齐</button>
            </div>
            <div class="adt-popover__group">
              <span class="adt-popover__label">任务编排</span>
              <router-link
                class="adt-btn adt-btn--block adt-btn--primary"
                :to="{ name: 'admin-orchestrate-jobs' }"
                @click="moreOpen = false"
              >任务编排流水</router-link>
            </div>
            <div class="adt-popover__group">
              <span class="adt-popover__label">运维入口</span>
              <router-link
                class="adt-btn adt-btn--block"
                :to="{ name: 'admin-yuangon-onboard' }"
                @click="moreOpen = false"
              >Yuangon 上架</router-link>
              <router-link
                class="adt-btn adt-btn--block"
                :to="{ name: 'admin-ops-audit' }"
                @click="moreOpen = false"
              >运维操作日志</router-link>
              <router-link
                class="adt-btn adt-btn--block"
                :to="{ name: 'admin-employee-autonomy' }"
                @click="moreOpen = false"
              >自治面板</router-link>
              <router-link
                class="adt-btn adt-btn--block"
                :to="{ name: 'admin-ai-accounts' }"
                @click="moreOpen = false"
              >AI 员工账号池</router-link>
            </div>
          </div>
        </div>

        <span v-if="alignMsg" class="adt-msg">{{ alignMsg }}</span>
        <span v-if="healthErr" class="adt-msg adt-msg--err">健康看板：{{ healthErr }}</span>
      </template>
    </AdminDutyEmployeeGraph>
  </div>
</template>

<style scoped>
.admin-duty-employees-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: 100%;
}

.adt-stat {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  border: 1px solid var(--color-border-subtle, #333);
  background: var(--color-bg-elevated, #1e1e2e);
  color: var(--color-text-muted, #aaa);
  font-size: 0.78rem;
  line-height: 1.2;
}
.adt-stat strong { color: var(--color-text-primary, #e0e0e0); }
.adt-stat--link { text-decoration: none; }
.adt-stat--btn {
  cursor: pointer;
  font: inherit;
  transition: background 0.15s, border-color 0.15s;
}
.adt-stat--btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
  border-color: var(--color-primary, #6366f1);
}
.adt-stat--btn:focus-visible {
  outline: 2px solid var(--color-primary, #6366f1);
  outline-offset: 2px;
}
.stat-warn { color: #f97316 !important; }

.adt-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.32rem 0.7rem;
  border-radius: 7px;
  border: 1px solid var(--color-border-subtle, #444);
  background: var(--color-bg-elevated, #1e1e2e);
  color: var(--color-text-primary, #e0e0e0);
  cursor: pointer;
  text-decoration: none;
  font-size: 0.82rem;
  line-height: 1.2;
  white-space: nowrap;
}
.adt-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.05); }
.adt-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.adt-btn--primary {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.2);
  color: #c7d2fe;
}
.adt-btn--primary:hover:not(:disabled) { background: rgba(99, 102, 241, 0.32); }
.adt-btn--ghost {
  background: transparent;
  border-color: var(--color-border-subtle, #444);
  color: var(--color-text-secondary, #bbb);
}
.adt-btn--active {
  border-color: #6366f1;
  color: #c7d2fe;
  background: rgba(99, 102, 241, 0.12);
}
.adt-btn--block {
  width: 100%;
  justify-content: center;
}

.adt-caret {
  font-size: 0.7rem;
  opacity: 0.8;
}

.adt-more {
  position: relative;
  display: inline-flex;
}
.adt-popover {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  z-index: 30;
  width: 240px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  border: 1px solid var(--color-border-subtle, #333);
  border-radius: 10px;
  background: var(--color-bg-elevated, #1a1a26);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.45);
}
.adt-popover__hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--color-text-muted, #888);
  line-height: 1.4;
}
.adt-popover__group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.adt-popover__label {
  font-size: 0.7rem;
  letter-spacing: 0.04em;
  color: var(--color-text-muted, #777);
  text-transform: uppercase;
}

.adt-msg {
  font-size: 0.78rem;
  color: var(--color-text-secondary, #ccc);
  max-width: 320px;
  line-height: 1.3;
}
.adt-msg--err { color: #f87171; }

.admin-duty-dispatch {
  padding: 0.75rem;
  border-bottom: 1px solid var(--color-border-subtle, #333);
  background: rgba(99, 102, 241, 0.05);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.admin-duty-dispatch textarea {
  width: 100%;
  padding: 0.5rem;
  border-radius: 6px;
  border: 1px solid var(--color-border-subtle, #444);
  background: var(--color-bg-base, #0d0d18);
  color: var(--color-text-primary, #e0e0e0);
  font-family: inherit;
  font-size: 0.9rem;
  resize: vertical;
}
.admin-duty-dispatch__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
}

.admin-duty-denied {
  padding: 2rem;
  text-align: center;
  color: var(--color-text-secondary, #aaa);
}
.btn {
  display: inline-block;
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  border-radius: 8px;
  text-decoration: none;
}
.btn-primary {
  background: #fff;
  color: #0a0a0a;
}
html[data-workbench-theme='light'] .adt-stat{background:#fff;color:#64748b;border-color:#e2e8f0}
html[data-workbench-theme='light'] .adt-stat--btn:hover:not(:disabled){background:rgba(99,102,241,0.06);border-color:#6366f1}
html[data-workbench-theme='light'] .adt-stat strong{color:#1a1a1a}
html[data-workbench-theme='light'] .stat-warn{color:#ea580c}
html[data-workbench-theme='light'] .adt-btn{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .adt-btn:hover{background:rgba(0,0,0,0.03)}
html[data-workbench-theme='light'] .adt-btn--primary{background:rgba(99,102,241,0.08);color:#4f46e5;border-color:#6366f1}
html[data-workbench-theme='light'] .adt-btn--primary:hover{background:rgba(99,102,241,0.14)}
html[data-workbench-theme='light'] .adt-btn--ghost{color:#64748b;border-color:#d1d5db}
html[data-workbench-theme='light'] .adt-btn--active{background:rgba(99,102,241,0.08);color:#4f46e5;border-color:#6366f1}
html[data-workbench-theme='light'] .adt-popover{background:#fff;border-color:#e2e8f0;box-shadow:0 12px 28px rgba(0,0,0,0.1)}
html[data-workbench-theme='light'] .adt-popover__hint{color:#94a3b8}
html[data-workbench-theme='light'] .adt-popover__label{color:#94a3b8}
html[data-workbench-theme='light'] .adt-msg{color:#64748b}
html[data-workbench-theme='light'] .adt-msg--err{color:#dc2626}
html[data-workbench-theme='light'] .admin-duty-dispatch{background:rgba(99,102,241,0.03);border-color:#e2e8f0}
html[data-workbench-theme='light'] .admin-duty-dispatch textarea{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .btn-primary{background:#1a1a1a;color:#fff}
</style>
