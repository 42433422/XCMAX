<script setup lang="ts">
/**
 * DutyRosterGraphPanel —— 在岗员工节点图（排班图）入口组件。
 * 模板拆分至 ./dutyRoster/ 子组件、业务逻辑拆分至 ./dutyRoster/useDuty*.ts；本文件仅保留组装胶水
 * （组合式函数实例化、跨模块衔接、路由同步与生命周期 watch），对外行为不变：props/emit/defineExpose、视觉结构均与拆分前一致。
 */
import { computed, nextTick, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVueFlow } from '@vue-flow/core'
import { useMarketAdminGraphAuth } from '@/composables/useMarketAdminGraphAuth'
import SelfEvolutionLoopRuntimePanel from '@/components/workflow/SelfEvolutionLoopRuntimePanel.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'
import DutyRosterHeader from './dutyRoster/DutyRosterHeader.vue'
import DutyNoKeyPanel from './dutyRoster/DutyNoKeyPanel.vue'
import DutyGapPanel from './dutyRoster/DutyGapPanel.vue'
import DutyRunPanel from './dutyRoster/DutyRunPanel.vue'
import DutyAllHandsPanel from './dutyRoster/DutyAllHandsPanel.vue'
import DutyFlowGraph from './dutyRoster/DutyFlowGraph.vue'
import DutyWorkshopDetail from './dutyRoster/DutyWorkshopDetail.vue'
import DutyEmployeeDetail from './dutyRoster/DutyEmployeeDetail.vue'

import { useDutyRosterState } from './dutyRoster/useDutyRosterState'
import { useDutySelection } from './dutyRoster/useDutySelection'
import { useDutyExec } from './dutyRoster/useDutyExec'
import { useDutyGap } from './dutyRoster/useDutyGap'
import { useDutyRosterData } from './dutyRoster/useDutyRosterData'
import { useDutyNoKey } from './dutyRoster/useDutyNoKey'
import { useDutyPanels } from './dutyRoster/useDutyPanels'
import { useDutyRun } from './dutyRoster/useDutyRun'
import { useDutyLoopCore } from './dutyRoster/useDutyLoopCore'
import { useDutyLoopGovernance } from './dutyRoster/useDutyLoopGovernance'
import { useDutyLoopDiagnosis } from './dutyRoster/useDutyLoopDiagnosis'
import { useDutyAllHands } from './dutyRoster/useDutyAllHands'
import { useDutyWorkshop } from './dutyRoster/useDutyWorkshop'
import { useDutyGraphBuild } from './dutyRoster/useDutyGraphBuild'
import {
  DEFAULT_GRAPH_VIEW_MODE,
  isGraphViewToken,
  normalizeViewToken,
  parseViewModeFromQuery,
  isVirtualEmployee,
} from './dutyRoster/dutyRosterConstants'
import type { EmpRow } from './dutyRoster/dutyRosterTypes'

const props = withDefaults(defineProps<{ open: boolean; variant?: 'modal' | 'page' | 'embedded' }>(), {
  variant: 'modal',
})
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const route = useRoute()
const isPage = computed(() => props.variant === 'page')
const isEmbedded = computed(() => props.variant === 'embedded')
const isInlineLayout = computed(() => isPage.value || isEmbedded.value)
const flowBgPatternColor = computed(() =>
  isInlineLayout.value ? 'rgba(15, 23, 42, 0.06)' : 'rgba(255,255,255,0.04)',
)
const miniMapMaskColor = computed(() =>
  isInlineLayout.value ? 'rgba(237, 243, 250, 0.85)' : 'rgba(0,0,0,0.45)',
)
const { currentMode } = useMarketAdminGraphAuth()
const { fitView } = useVueFlow('admin-duty-graph')

// ── 共享状态（useDutyRosterState）—— 全部 ref/computed 原样解构，响应性保持 ──
const state = useDutyRosterState(route)
const {
  employees, error, loadWarning, loading, loadingP2, viewMode, showGapPanel, gapFocusHint,
  showNoKeyPanel, showRunPanel, showAllHandsPanel, allHandsBusy, allHandsSessionId, autoRefresh,
  runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency,
  latestRun, runNodeStatusMap, flowNodes, flowEdges, selectedEmp, selectedWorkshop, showDispatch,
  runBusy, runError,
  taskResult, taskError, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning,
  noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, execItems, execTotal, execLoading,
  execLoadingMore, execError, llmStatusFailed, llmStatusMap, capLoading, countdown, healthLevel,
  showStatsDetail, showMoreActions, allHandsError, allHandsExpanded, allHandsMeetingMinutes,
  allHandsMeetingMinutesEmail, allHandsPlainLoading, allHandsPlainOpen, allHandsPlainText,
  allHandsProgress, allHandsReport, allHandsQuestion, allHandsWithResearch, workshopRouteCopied,
} = state

// ── 胶水函数（原文机械搬移，行为不变）──
function clampDutyRosterGraphViewQuery(raw: unknown): void {
  const nextQuery = { ...route.query }
  if (raw == null || String(Array.isArray(raw) ? raw[0] : raw).trim() === '') {
    if (route.query.view === DEFAULT_GRAPH_VIEW_MODE) return
    nextQuery.view = DEFAULT_GRAPH_VIEW_MODE
    void router.replace({ query: nextQuery })
    return
  }
  const viewText = normalizeViewToken(raw)
  if (!isGraphViewToken(viewText)) {
    delete nextQuery.view
    void router.replace({ query: nextQuery })
    return
  }
}

function readDutyRosterViewFromRoute() {
  viewMode.value = parseViewModeFromQuery(route.query.view)
  clampDutyRosterGraphViewQuery(route.query.view)
}

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
    Promise.resolve(fitView({ nodes: [trimmed], padding: 0.35, duration: 400 })).catch(() => {
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

function goBackFromPage() {
  if (typeof window !== 'undefined' && window.history.length > 1) {
    router.back()
    return
  }
  if (router.hasRoute('duty-roster-graph')) {
    void router.push({ name: 'duty-roster-graph', query: { view: 'department' } })
    return
  }
  if (router.hasRoute('other-tools')) {
    void router.push({ name: 'other-tools' })
    return
  }
  if (router.hasRoute('admin-database')) {
    void router.push({ name: 'admin-database' })
    return
  }
  void router.push({ name: 'chat' })
}

function goUse(emp: EmpRow) {
  currentMode.value = 'client'
  if (!isPage.value) emit('close')
  if (isVirtualEmployee(emp.id)) {
    // 数字管家是常驻浮窗，没有独立工作台路由；带管理员到技能管理页
    void router.push({ name: 'admin-butler-skills' })
    return
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

defineExpose({ openGapPanel, focusEmployee })

// ── 组合式函数装配（依赖顺序与原文数据流一致）──
const selection = useDutySelection(state)
const exec = useDutyExec(state)
const gap = useDutyGap(state)
const { gapRows, gapSummary } = gap
const data = useDutyRosterData(state, { applyEmployeeQueryFromRoute })
const { load, stopAutoRefresh } = data
const nokey = useDutyNoKey(state, data, { router })
const { loadNoKeyEmployees, alignSingleEmployeeToAuto, gotoAddKey } = nokey
const panels = useDutyPanels(state, nokey)
const { closeOtherPanels, togglePanel, openNoKeyPanel, isDetailOpen, toggleDetail } = panels
const run = useDutyRun(state, data, exec, selection)
const { startGraphRun, stopRunPolling, dispatchTask, publishTaskToButler } = run
const core = useDutyLoopCore(state, { focusEmployee, router })
const {
  nodeLoopActive, employeeSpaceLocation, loopOpenRunCount, loopParticipantIdSet, loopParticipantIds,
  loopRuntimeContractStatus, loopRuntimeStatus,
} = core
const gov = useDutyLoopGovernance(state, core)
const { loopStatusLabel } = gov
const diag = useDutyLoopDiagnosis(state, core, gov, { load })
const { loopParticipantList, selectedLoopParticipant, selectedLoopTimelineSummary, selectedLoopContext } = diag
const allhands = useDutyAllHands(state, panels, { focusEmployee })
const {
  stopAllHandsPolling, resetAllHandsProgress, runAllHands, askAllHandsQuestion, toggleAllHandsRow,
  requestPlainLang, publishFollowUpToButler, copyAllHandsMeetingMinutes, downloadAllHandsMeetingMinutes,
  focusAllHandsEmployee, allHandsAreaPalette,
} = allhands
const workshop = useDutyWorkshop(state, { focusEmployee, syncEmployeeRouteQuery, router })
const {
  onNodeClick: handleNodeClick, focusEmployeeFromWorkshop, openSelectedWorkshopInClient,
  copySelectedWorkshopRoute, selectedWorkshopLinkedEmployees, selectedWorkshopRouteHref,
} = workshop
const { stats } = useDutyGraphBuild(state, core, data, { fitView, syncEmployeeRouteQuery })
const { selectedHealth, selectedDeps, selectedCapabilityView, isSelectedVirtual,
  selectedLlm, selectedCapability, selectedRunNode } = selection
const { fetchExecMetrics } = exec

// ── 路由 / 生命周期 watch（原文机械搬移）──
readDutyRosterViewFromRoute()

watch(
  () => route.query.view,
  () => { readDutyRosterViewFromRoute() },
)

watch(
  () => route.query.employee,
  () => { void applyEmployeeQueryFromRoute() },
)

watch(
  () => [props.open, props.variant] as const,
  ([open, variant]) => {
    const active = variant === 'page' || variant === 'embedded' || open
    if (active) {
      void load()
    } else {
      stopAutoRefresh()
      stopRunPolling()
      stopAllHandsPolling()
      autoRefresh.value = false
      allHandsBusy.value = false
      allHandsSessionId.value = ''
      resetAllHandsProgress()
      selectedEmp.value = null
      showGapPanel.value = false
      latestRun.value = null
      runNodeStatusMap.value = {}
    }
  },
  { immediate: true },
)

watch(
  employees,
  (rows) => {
    if (!rows.length) {
      runTargetId.value = ''
      return
    }
    if (!rows.some((r) => r.id === runTargetId.value)) {
      runTargetId.value = rows[0].id
    }
  },
  { deep: true },
)

onUnmounted(() => {
  stopAutoRefresh()
  stopRunPolling()
  stopAllHandsPolling()
})
</script>
<template>
  <Teleport :disabled="isInlineLayout" to="body">
    <transition name="dg-fade">
      <div
        v-if="isInlineLayout || open"
        :class="isInlineLayout ? 'dg-page-root dg-page-root--office' : 'dg-overlay'"
        :role="isPage ? undefined : isEmbedded ? undefined : 'dialog'"
        :aria-modal="isPage || isEmbedded ? undefined : true"
        aria-label="在岗员工节点图"
        @click.self="onBackdropClick"
      >
        <div :class="['dg-panel', isInlineLayout && 'dg-panel--page dg-panel--office', isEmbedded && 'dg-panel--embedded']">

          <!-- ══ Header ══════════════════════════════════════════════════════ -->
            <DutyRosterHeader
              v-model:show-stats-detail="showStatsDetail"
              v-model:view-mode="viewMode"
              v-model:show-more-actions="showMoreActions"
              v-model:auto-refresh="autoRefresh"
              :open="open"
              :is-page="isPage"
              :go-back-from-page="goBackFromPage"
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
              :loop-runtime-status="loopRuntimeStatus"
              :loop-runtime-contract-status="loopRuntimeContractStatus"
              :loop-status-label="loopStatusLabel"
              :loop-open-run-count="loopOpenRunCount"
              :loop-participant-id-set="loopParticipantIdSet"
              :loop-participant-ids="loopParticipantIds"
              :employee-space-location="employeeSpaceLocation"
              :open-no-key-panel="openNoKeyPanel"
              :toggle-panel="togglePanel"
              @close="$emit('close')"
            >
              <template v-if="$slots.pageActions" #pageActions>
                <slot name="pageActions" />
              </template>
            </DutyRosterHeader>
          <!-- ══ Error / 降级提示 ═══════════════════════════════════════════ -->
          <p v-if="error" class="dg-error">
            {{ error }}&nbsp;<button class="dg-btn--inline" @click="load">重试</button>
          </p>
          <p v-else-if="loadWarning" class="dg-error dg-error--warn">
            {{ loadWarning }}（已展示本机编制，部分运维数据可能不可用）&nbsp;
            <button class="dg-btn--inline" @click="load">重试</button>
          </p>
          <!-- ══ Body ═════════════════════════════════════════════════════════ -->
          <div class="dg-body">

            <!-- ── No-key panel：点 dg-stats「✗ 无密钥」打开 ──────────────────── -->
            <DutyNoKeyPanel
              v-model:show-no-key-panel="showNoKeyPanel"
              :no-key-loading="noKeyLoading"
              :no-key-error="noKeyError"
              :no-key-data="noKeyData"
              :no-key-busy-row="noKeyBusyRow"
              :load-no-key-employees="loadNoKeyEmployees"
              :align-single-employee-to-auto="alignSingleEmployeeToAuto"
              :goto-add-key="gotoAddKey"
            />
            <DutyGapPanel
              :show-gap-panel="showGapPanel"
              :gap-focus-hint="gapFocusHint"
              :gap-rows="gapRows"
              :gap-summary="gapSummary"
              :focus-employee="focusEmployee"
            />
            <DutyRunPanel
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
            <DutyAllHandsPanel
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
            <SelfEvolutionLoopRuntimePanel
              v-if="viewMode === 'loop'"
              class="dg-loop-runtime-panel"
              surface="duty-roster"
            />

            <!-- ── Empty state ───────────────────────────────────────────── -->
            <div v-else-if="!loading && employees.length === 0" class="dg-empty">
              <p>暂无在岗员工包。<br />请先在工作台生成并发布员工包。</p>
            </div>

            <!-- ── Flow + detail ─────────────────────────────────────────── -->
            <div v-else class="dg-flow-wrap">
            <DutyFlowGraph
              :flow-nodes="flowNodes"
              :flow-edges="flowEdges"
              :flow-bg-pattern-color="flowBgPatternColor"
              :mini-map-mask-color="miniMapMaskColor"
              :node-loop-active="nodeLoopActive"
              :handle-node-click="handleNodeClick"
            />
            <DutyWorkshopDetail
              v-model:selected-workshop="selectedWorkshop"
              :view-mode="viewMode"
              :workshop-route-copied="workshopRouteCopied"
              :selected-workshop-linked-employees="selectedWorkshopLinkedEmployees"
              :selected-workshop-route-href="selectedWorkshopRouteHref"
              :open-selected-workshop-in-client="openSelectedWorkshopInClient"
              :copy-selected-workshop-route="copySelectedWorkshopRoute"
              :focus-employee-from-workshop="focusEmployeeFromWorkshop"
            />
            <DutyEmployeeDetail
              v-model:view-mode="viewMode"
              v-model:show-dispatch="showDispatch"
              v-model:task-brief="taskBrief"
              v-model:task-input-json="taskInputJson"
              v-model:dispatch-confirm-high-risk="dispatchConfirmHighRisk"
              v-model:selected-emp="selectedEmp"
              :cap-loading="capLoading"
              :loading-p2="loadingP2"
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
              :loop-participant-list="loopParticipantList"
              :selected-loop-participant="selectedLoopParticipant"
              :selected-loop-timeline-summary="selectedLoopTimelineSummary"
              :selected-loop-context="selectedLoopContext"
              :employee-space-location="employeeSpaceLocation"
              :go-use="goUse"
              :account-keys-nav="onAccountKeysNav"
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
