<script setup lang="ts">
/**
 * AdminDutyEmployeeGraph —— 管理端在岗员工节点图（排班图）入口组件。
 *
 * 模板已拆分至 ./adminDuty/ 子组件、业务逻辑拆分至 ./adminDuty/useAdminDuty*.ts。
 * 本文件仅保留组装胶水（组合式函数装配、跨模块衔接、路由同步与生命周期 watch），
 * 对外行为与拆分前一致：props / emit / defineExpose、视觉结构不变。
 */
import { computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVueFlow } from '@vue-flow/core'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '../../stores/auth'
import { createEmptyEmployeeConfigV2 } from '../../employeeConfigV2'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

// 子组件（模板块切分）
import AdminDutyHeader from './adminDuty/AdminDutyHeader.vue'
import AdminDutyNoKeyPanel from './adminDuty/AdminDutyNoKeyPanel.vue'
import AdminDutyGapPanel from './adminDuty/AdminDutyGapPanel.vue'
import AdminDutyRunPanel from './adminDuty/AdminDutyRunPanel.vue'
import AdminDutyAllHandsPanel from './adminDuty/AdminDutyAllHandsPanel.vue'
import AdminDutyFlowCanvas from './adminDuty/AdminDutyFlowCanvas.vue'
import AdminDutyWorkshopDetail from './adminDuty/AdminDutyWorkshopDetail.vue'
import AdminDutyEmployeeDetail from './adminDuty/AdminDutyEmployeeDetail.vue'

// 组合式函数（业务逻辑切分）
import { useAdminDutyState } from './adminDuty/useAdminDutyState'
import { useAdminDutyData } from './adminDuty/useAdminDutyData'
import { useAdminDutyNoKey } from './adminDuty/useAdminDutyNoKey'
import { useAdminDutyPanels } from './adminDuty/useAdminDutyPanels'
import { useAdminDutyGap } from './adminDuty/useAdminDutyGap'
import { useAdminDutySelection } from './adminDuty/useAdminDutySelection'
import { useAdminDutyExec } from './adminDuty/useAdminDutyExec'
import { useAdminDutyRun } from './adminDuty/useAdminDutyRun'
import { useAdminDutyAllHands } from './adminDuty/useAdminDutyAllHands'
import { useAdminDutyWorkshop } from './adminDuty/useAdminDutyWorkshop'
import { useAdminDutyGraphBuild } from './adminDuty/useAdminDutyGraphBuild'
import { useAdminDutyWatches } from './adminDuty/useAdminDutyWatches'
import { createAdminDutyLayout } from './adminDuty/adminDutyLayout'
// 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定；
// <script setup> 的 setupState 仅包含顶层声明（不含未在模板使用的 import），
// 故以 namespace 导入后解构为顶层 const。
import * as adminDutyConstants from './adminDuty/adminDutyConstants'
/* eslint-disable @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定 */
const {
  isVirtualEmployee, isDutyGraphMember, isDeployedDutyRosterRow,
  craftEmployeeDependsOn, allHandsAreaPalette,
  formatDurationMs, formatRate, formatTime,
} = adminDutyConstants
/* eslint-enable @typescript-eslint/no-unused-vars */
import type { EmpRow } from './adminDuty/adminDutyTypes'

const props = withDefaults(defineProps<{ open: boolean; variant?: 'modal' | 'page' }>(), {
  variant: 'modal',
})
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const route = useRoute()
const isPage = computed(() => props.variant === 'page')
const authStore = useAuthStore()
const { currentMode } = storeToRefs(authStore)
const { fitView } = useVueFlow({ id: 'admin-duty-graph' })

// ── 共享状态（ref/computed 原样解构，响应性保持）──
const state = useAdminDutyState()
const {
  employees, error, loading, loadingP2, viewMode, showGapPanel, gapFocusHint,
  showNoKeyPanel, showRunPanel, showAllHandsPanel, allHandsBusy, allHandsSessionId, autoRefresh,
  runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk,
  runMaxConcurrency, latestRun, runNodeStatusMap, flowNodes, flowEdges, runBusy, runError,
  selectedEmp, selectedWorkshop, workshopRouteCopied, showDispatch, taskResult, taskError,
  taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, noKeyData, noKeyLoading,
  noKeyError, noKeyBusyRow, execItems, execTotal, execLoading, execLoadingMore, execError,
  llmStatusFailed, llmStatusMap, capLoading, countdown, healthLevel, showStatsDetail,
  showMoreActions, allHandsError, allHandsExpanded, allHandsMeetingMinutes,
  allHandsMeetingMinutesEmail, allHandsPlainLoading, allHandsPlainOpen, allHandsPlainText,
  allHandsProgress, allHandsReport, allHandsQuestion, allHandsWithResearch,
  capabilityLabel, llmActLevel,
  // 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定
  healthMap, depsMap, empLlmMap, capabilityMap, onDutyEmployees,
  runStatusLevel, empAreaColor, capabilityLevel, capabilityColor,
} = state

// ── 胶水函数（原文机械搬移，行为不变）──
function focusEmployee(id: string) {
  const trimmed = String(id || '').trim()
  if (!trimmed) return
  gapFocusHint.value = ''
  const emp = employees.value.find((e) => e.id === trimmed)
  if (!emp) {
    showGapPanel.value = true
    gapFocusHint.value = `未找到员工「${trimmed}」`
    selectedEmp.value = null
    return
  }
  if (emp.source === 'v1_catalog') {
    showGapPanel.value = true
    gapFocusHint.value = `岗位「${emp.name || emp.id}」尚未上架 Catalog，请在桌面服务器后台补登记`
    selectedEmp.value = null
    return
  }
  selectedEmp.value = emp
  runTargetId.value = emp.id
  showDispatch.value = false
  taskResult.value = null
  taskError.value = null
  syncEmployeeRouteQuery(emp.id)
  nextTick(() => {
    void fitView({ nodes: [trimmed], padding: 0.35, duration: 400 }).catch(() => {
      void fitView({ padding: 0.12, duration: 300 })
    })
  })
}

function syncEmployeeRouteQuery(employeeId?: string | null) {
  if (!isPage.value) return
  const nextQuery = { ...route.query }
  const id = String(employeeId || '').trim()
  if (id) nextQuery.employee = id
  else delete nextQuery.employee
  void router.replace({ query: nextQuery })
}

async function applyEmployeeQueryFromRoute() {
  const raw = route.query.employee
  const id = typeof raw === 'string'
    ? raw.trim()
    : Array.isArray(raw)
      ? String(raw[0] || '').trim()
      : ''
  if (!id || loading.value || !employees.value.length) return
  focusEmployee(id)
}

function buildDutyGraphEmployeePrefill(emp: EmpRow): Record<string, unknown> {
  const base = createEmptyEmployeeConfigV2() as Record<string, unknown>
  const ident = { ...(base.identity as Record<string, unknown>), id: emp.id, name: emp.name || emp.id }
  return {
    ...base,
    id: emp.id,
    name: emp.name || emp.id,
    identity: ident,
  }
}

function goUse(emp: EmpRow) {
  currentMode.value = 'client'
  if (!isPage.value) emit('close')
  if (isVirtualEmployee(emp.id)) {
    // 数字管家是常驻浮窗，没有独立工作台路由；带管理员到技能管理页
    void router.push({ name: 'admin-butler-skills' })
    return
  }
  if (emp.source === 'v1_catalog') {
    try {
      sessionStorage.setItem('modstore_employee_prefill', JSON.stringify(buildDutyGraphEmployeePrefill(emp)))
    } catch {
      /* quota / private mode */
    }
  }
  void router.push({ name: 'workbench-shell', params: { target: 'employee' }, query: { packId: emp.id, fromDutyGraph: '1' } })
}

function onAccountKeysNav() {
  if (!isPage.value) emit('close')
}

function onBackdropClick() {
  if (!isPage.value) emit('close')
}

/** 值班页工具栏「缺岗 N」：打开缺岗分析面板 */
function openGapPanel() {
  closeOtherPanels('gap')
  showGapPanel.value = true
  gapFocusHint.value = ''
}

// ── 组合式函数装配（依赖顺序与原文数据流一致）──
const data = useAdminDutyData(state, { applyEmployeeQueryFromRoute })
const { load, stopAutoRefresh, startAutoRefresh, loadPhase2, loadCapabilities, buildRosterEmployeeRows } = data
const layout = createAdminDutyLayout({
  flowNodes, flowEdges, depsMap, healthLevel, llmActLevel, runStatusLevel,
  empAreaColor, capabilityLevel, capabilityColor,
  buildRosterEmployeeRows,
})
// 测试兼容面：图构建函数保留顶层解构维持 wrapper.vm 暴露面（重建调用已迁至 useAdminDutyWatches）
const { buildAreaGraph, buildHubGraph, buildDepartmentGraph, buildClientWorkshopGraph } = layout
const graphbuild = useAdminDutyGraphBuild(state, layout, { fitView, syncEmployeeRouteQuery })
const { stats } = graphbuild
const nokey = useAdminDutyNoKey(state, data, { router })
const { loadNoKeyEmployees, alignSingleEmployeeToAuto, gotoAddKey } = nokey
const panels = useAdminDutyPanels(state, nokey)
const { closeOtherPanels, openNoKeyPanel, togglePanel, isDetailOpen, toggleDetail } = panels
const gap = useAdminDutyGap(state)
const { gapRows, gapSummary } = gap
const selection = useAdminDutySelection(state)
const { selectedHealth, selectedDeps, selectedCapabilityView, isSelectedVirtual, selectedLlm, selectedCapability, selectedRunNode } = selection
const exec = useAdminDutyExec(state)
const { fetchExecMetrics } = exec
const run = useAdminDutyRun(state, data, selection, exec)
const { startGraphRun, stopRunPolling, pollRunDetail, dispatchTask, publishTaskToButler } = run
const allhands = useAdminDutyAllHands(state, panels, { focusEmployee })
const {
  stopAllHandsPolling, resetAllHandsProgress, runAllHands, askAllHandsQuestion, toggleAllHandsRow,
  requestPlainLang, publishFollowUpToButler, focusAllHandsEmployee, copyAllHandsMeetingMinutes,
  downloadAllHandsMeetingMinutes, applyAllHandsProgress,
  applyAllHandsReport, // eslint-disable-line @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问
  parseAllHandsReportFromArtifact, pollAllHandsSession,
} = allhands
const workshop = useAdminDutyWorkshop(state, { focusEmployee, syncEmployeeRouteQuery, router })
const {
  onNodeClick,
  onClientWorkshopNodeClick, // eslint-disable-line @typescript-eslint/no-unused-vars -- 测试兼容面：既有测试经 setupState 访问
  focusEmployeeFromWorkshop, openSelectedWorkshopInClient,
  copySelectedWorkshopRoute, selectedWorkshopLinkedEmployees, selectedWorkshopRouteHref,
} = workshop

/** 模板 onClose 兜底（保留原 accountKeysNav 行为入口名）。 */
const accountKeysNav = onAccountKeysNav


// ── watch / 生命周期装配（原文机械迁出至 ./adminDuty/useAdminDutyWatches.ts，行为不变）──
useAdminDutyWatches({
  state, layout, props, route, fitView,
  syncEmployeeRouteQuery, applyEmployeeQueryFromRoute,
  data, run, allhands, exec,
})

defineExpose({
  capabilityLabel,
  openGapPanel,
  focusEmployee,
  __coverage: {
    alignSingleEmployeeToAuto,
    applyAllHandsProgress,
    buildAreaGraph,
    dispatchTask,
    fetchExecMetrics,
    focusEmployee,
    load,
    loadCapabilities,
    loadNoKeyEmployees,
    loadPhase2,
    parseAllHandsReportFromArtifact,
    pollAllHandsSession,
    pollRunDetail,
    publishTaskToButler,
    runAllHands,
    startAutoRefresh,
    startGraphRun,
    stopAllHandsPolling,
    stopAutoRefresh,
    stopRunPolling,
  },
})
</script>
<template>
  <Teleport :disabled="isPage" to="body">
    <transition name="dg-fade">
      <div
        v-if="isPage || open"
        :class="isPage ? 'dg-page-root' : 'dg-overlay'"
        :role="isPage ? undefined : 'dialog'"
        :aria-modal="isPage ? undefined : true"
        aria-label="在岗员工节点图"
        @click.self="onBackdropClick"
      >
        <div :class="['dg-panel', isPage && 'dg-panel--page']">

          <!-- ══ Header ══════════════════════════════════════════════════════ -->
          <AdminDutyHeader
            v-model:show-stats-detail="showStatsDetail"
            v-model:view-mode="viewMode"
            v-model:show-more-actions="showMoreActions"
            v-model:auto-refresh="autoRefresh"
            :open="open"
            :is-page="isPage"
            :router="router"
            :load="load"
            :employees="employees"
            :loading="loading"
            :loading-p2="loadingP2"
            :cap-loading="capLoading"
            :countdown="countdown"
            :llm-status-failed="llmStatusFailed"
            :selected-emp="selectedEmp"
            :show-gap-panel="showGapPanel"
            :show-no-key-panel="showNoKeyPanel"
            :show-run-panel="showRunPanel"
            :show-all-hands-panel="showAllHandsPanel"
            :all-hands-busy="allHandsBusy"
            :gap-summary="gapSummary"
            :stats="stats"
            :open-no-key-panel="openNoKeyPanel"
            :toggle-panel="togglePanel"
            @close="emit('close')"
          >
            <template v-if="$slots.pageActions" #pageActions>
              <slot name="pageActions" />
            </template>
          </AdminDutyHeader>

          <!-- ══ Error ════════════════════════════════════════════════════════ -->
          <p v-if="error" class="dg-error">
            {{ error }}&nbsp;<button class="dg-btn--inline" @click="load">重试</button>
          </p>

          <!-- ══ Body ═════════════════════════════════════════════════════════ -->
          <div v-if="!error" class="dg-body">

            <!-- ── No-key panel：点 dg-stats「✗ 无密钥」打开 ──────────────────── -->
            <AdminDutyNoKeyPanel
              v-model:show-no-key-panel="showNoKeyPanel"
              :no-key-loading="noKeyLoading"
              :no-key-error="noKeyError"
              :no-key-data="noKeyData"
              :no-key-busy-row="noKeyBusyRow"
              :load-no-key-employees="loadNoKeyEmployees"
              :align-single-employee-to-auto="alignSingleEmployeeToAuto"
              :goto-add-key="gotoAddKey"
            />
            <AdminDutyGapPanel
              :show-gap-panel="showGapPanel"
              :gap-focus-hint="gapFocusHint"
              :gap-rows="gapRows"
              :gap-summary="gapSummary"
              :focus-employee="focusEmployee"
            />
            <AdminDutyRunPanel
              v-model:run-target-id="runTargetId"
              v-model:run-max-concurrency="runMaxConcurrency"
              v-model:run-task-brief="runTaskBrief"
              v-model:run-input-json="runInputJson"
              v-model:run-include-dependencies="runIncludeDependencies"
              v-model:run-allow-high-risk="runAllowHighRisk"
              :show-run-panel="showRunPanel"
              :run-busy="runBusy"
              :run-error="runError"
              :latest-run="latestRun"
              :employees="employees"
              :start-graph-run="startGraphRun"
            />
            <AdminDutyAllHandsPanel
              v-model:all-hands-with-research="allHandsWithResearch"
              v-model:show-all-hands-panel="showAllHandsPanel"
              v-model:all-hands-question="allHandsQuestion"
              :all-hands-busy="allHandsBusy"
              :all-hands-error="allHandsError"
              :all-hands-expanded="allHandsExpanded"
              :all-hands-meeting-minutes="allHandsMeetingMinutes"
              :all-hands-meeting-minutes-email="allHandsMeetingMinutesEmail"
              :all-hands-plain-loading="allHandsPlainLoading"
              :all-hands-plain-open="allHandsPlainOpen"
              :all-hands-plain-text="allHandsPlainText"
              :all-hands-progress="allHandsProgress"
              :all-hands-report="allHandsReport"
              :all-hands-session-id="allHandsSessionId"
              :employees="employees"
              :all-hands-area-palette="allHandsAreaPalette"
              :ask-all-hands-question="askAllHandsQuestion"
              :copy-all-hands-meeting-minutes="copyAllHandsMeetingMinutes"
              :download-all-hands-meeting-minutes="downloadAllHandsMeetingMinutes"
              :focus-all-hands-employee="focusAllHandsEmployee"
              :publish-follow-up-to-butler="publishFollowUpToButler"
              :request-plain-lang="requestPlainLang"
              :run-all-hands="runAllHands"
              :toggle-all-hands-row="toggleAllHandsRow"
            />

            <!-- ── Empty state ───────────────────────────────────────────── -->
            <div v-if="!loading && employees.length === 0" class="dg-empty">
              <p>暂无在岗员工包。<br />请先在工作台生成并发布员工包。</p>
            </div>

            <!-- ── Flow + detail ─────────────────────────────────────────── -->
            <div v-else class="dg-flow-wrap">
              <AdminDutyFlowCanvas
                :flow-nodes="flowNodes"
                :flow-edges="flowEdges"
                :handle-node-click="onNodeClick"
              />

              <!-- ── 客户端车间详情（仅管理端） ───────────────────────────── -->
              <AdminDutyWorkshopDetail
                v-model:selected-workshop="selectedWorkshop"
                :view-mode="viewMode"
                :workshop-route-copied="workshopRouteCopied"
                :selected-workshop-linked-employees="selectedWorkshopLinkedEmployees"
                :selected-workshop-route-href="selectedWorkshopRouteHref"
                :open-selected-workshop-in-client="openSelectedWorkshopInClient"
                :copy-selected-workshop-route="copySelectedWorkshopRoute"
                :focus-employee-from-workshop="focusEmployeeFromWorkshop"
              />

              <!-- ── Detail sidebar ──────────────────────────────────────── -->
              <AdminDutyEmployeeDetail
                v-model:selected-emp="selectedEmp"
                v-model:show-dispatch="showDispatch"
                v-model:task-brief="taskBrief"
                v-model:task-input-json="taskInputJson"
                v-model:dispatch-confirm-high-risk="dispatchConfirmHighRisk"
                :view-mode="viewMode"
                :exec-items="execItems"
                :exec-total="execTotal"
                :exec-loading="execLoading"
                :exec-loading-more="execLoadingMore"
                :exec-error="execError"
                :task-error="taskError"
                :task-result="taskResult"
                :task-running="taskRunning"
                :llm-status-map="llmStatusMap"
                :health-level="healthLevel"
                :selected-health="selectedHealth"
                :selected-deps="selectedDeps"
                :selected-capability-view="selectedCapabilityView"
                :is-selected-virtual="isSelectedVirtual"
                :selected-llm="selectedLlm"
                :selected-capability="selectedCapability"
                :selected-run-node="selectedRunNode"
                :fetch-exec-metrics="fetchExecMetrics"
                :dispatch-task="dispatchTask"
                :publish-task-to-butler="publishTaskToButler"
                :is-detail-open="isDetailOpen"
                :toggle-detail="toggleDetail"
                :loading-p2="loadingP2"
                :cap-loading="capLoading"
                :go-use="goUse"
                :account-keys-nav="accountKeysNav"
              />
            </div>

            <!-- Loading overlay (inside body — must not cover dg-header-actions) -->
            <div v-if="loading" class="dg-loading">
              <span class="dg-spinner" />
              正在拉取在岗员工列表…
            </div>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped src="./AdminDutyEmployeeGraph.css"></style>
