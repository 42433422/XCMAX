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

<script setup lang="ts">
// 拆分后本文件为组装入口（façade）：逻辑在 ./left-rail/，样式在 ./left-rail/left-rail.css。
import { ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { useWorkbenchStore } from '../../../stores/workbench'
import { useAgentLoop } from '../../../composables/useAgentLoop'
import { useAuthStore } from '../../../stores/auth'
import { isPlannedDutyRosterPkgId as isDutyRosterEmployee } from '../../../utils/workbenchEmployeeFilter'
import EmployeeAiDraftReview from '../../../components/workbench/EmployeeAiDraftReview.vue'
import { useLeftRailEmployees } from './left-rail/useLeftRailEmployees'
import { useLeftRailAgent } from './left-rail/useLeftRailAgent'
import type { RailView } from './left-rail/useLeftRailAgent'

const store = useWorkbenchStore()
const agentLoop = useAgentLoop()
const route = useRoute()

const auth = useAuthStore()
const { isAdmin } = storeToRefs(auth)

const view = ref<RailView>('list')

const emit = defineEmits<{
  (e: 'select-employee', id: string): void
}>()

function selectEmployee(id: string) {
  emit('select-employee', id)
}

const {
  employees,
  hiddenPkgIds,
  loadingList,
  listError,
  deletingId,
  purgeBusy,
  visibleEmployees,
  _hasV1OnlyEmployees,
  loadEmployees,
  confirmDeleteEmployee,
  purgeAllEmployees,
  hideLocally,
  clearHiddenPkgIds,
} = useLeftRailEmployees({ isAdmin, selectEmployee, route })

const {
  agentInput,
  agentRunning,
  runAgentDraft,
  retryEmployeeDraft,
  onDraftPublished,
  abortCurrentRun,
  applyRunManifest,
  formatTs,
  AGENT_SUGGESTED,
  useSuggestion,
} = useLeftRailAgent({ store, agentLoop, view, loadEmployees })
</script>

<style scoped src="./left-rail/left-rail.css"></style>
