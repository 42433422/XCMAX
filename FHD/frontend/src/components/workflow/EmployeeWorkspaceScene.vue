<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useNowMsTicker, useWorkflowEmployeeDesks } from '@/composables/useWorkflowEmployeeDesks'
import YuangongStation from '@/components/workflow/YuangongStation.vue'
import WorkflowEmployeeInspector from '@/components/workflow/WorkflowEmployeeInspector.vue'
import { YUANGONG_ENTRY_STITCH_PNG, YUANGONG_ENTRY_WORKFLOW_PNG, YUANGONG_ENTRY_WORKFLOW_SVG } from '@/constants/yuangongAssets'
import DutyRosterWorkflowLoopView from '@/components/workflow/DutyRosterWorkflowLoopView.vue'
import SelfEvolutionLoopRuntimePanel from '@/components/workflow/SelfEvolutionLoopRuntimePanel.vue'
import EmployeeWorkspaceLoopConsole from '@/components/employeeWorkspace/EmployeeWorkspaceLoopConsole.vue'
import { useDutyRoster } from '@/composables/useDutyRoster'
import { workflowRegistryEntryBelongsToStack } from '@/utils/workflowEmployeeScope'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import { useWorkflowEmployeeRegistrySync } from '@/composables/useWorkflowEmployeeRegistrySync'
import { useLoopRuntimeConsole } from '@/composables/useLoopRuntimeConsole'
import { useWorkspaceDeskSelection } from '@/composables/useWorkspaceDeskSelection'
import { useWorkspaceDeskDisplay } from '@/composables/useWorkspaceDeskDisplay'

const ENTRY_BG_STITCH = YUANGONG_ENTRY_STITCH_PNG
const ENTRY_BG_WORKFLOW_PNG = YUANGONG_ENTRY_WORKFLOW_PNG
const ENTRY_BG_WORKFLOW_SVG = YUANGONG_ENTRY_WORKFLOW_SVG

const isAdminConsole = isAdminConsoleSpa()
const showManagementLoopPanels = computed(() => isAdminConsole)
// SSOT 派生：运行时从后端 /api/system/duty-roster 获取编制矩阵
const {
  allPlannedIds: ALL_PLANNED_YUANGON_PKG_IDS,
  employeeLabels: YUANGON_PKG_ROLE_LABELS,
  ensureLoaded: ensureDutyRosterLoaded,
} = useDutyRoster()
useWorkflowEmployeeRegistrySync()
const { desks, statusLine, ariaLabel, isBusy } = useWorkflowEmployeeDesks()
const nowMs = useNowMsTicker(30000)

const enterpriseStack = ref<EnterpriseModStack | null>(null)

/** 企业 Mod 栈内 AI 员工工位（排除平台编制 employee_pack 等游离项） */
const workspaceDesks = computed(() => {
  const stack = enterpriseStack.value
  const filtered = desks.value.filter((d) => {
    // 管理端只显示平台编制员工（ALL_PLANNED_YUANGON_PKG_IDS，SSOT 派生），隔离企业 Mod 栈员工（如 attendance_ai 等）
    if (showManagementLoopPanels.value && !ALL_PLANNED_YUANGON_PKG_IDS.value.has(d.empId)) return false
    return workflowRegistryEntryBelongsToStack(d, stack)
  })
  // 管理端：工作流注册表无平台编制员工时，从 SSOT 54 岗构建占位工位，确保编制员工可见
  if (showManagementLoopPanels.value && filtered.length === 0) {
    return [...ALL_PLANNED_YUANGON_PKG_IDS.value].map((id) => ({
      empId: id,
      panelTitle: `工作流 · ${YUANGON_PKG_ROLE_LABELS.value[id] ?? id}`,
      shortName: YUANGON_PKG_ROLE_LABELS.value[id] ?? id,
      enabled: false,
    }))
  }
  return filtered
})

const { selectedEmpId, routeFocusedEmployeeId, routeFocusedEmployeeInWorkspace, selectDesk } = useWorkspaceDeskSelection(workspaceDesks)

const entryBgUrl = ref(ENTRY_BG_STITCH)

function onEntryBgError() {
  if (entryBgUrl.value === ENTRY_BG_STITCH) {
    entryBgUrl.value = ENTRY_BG_WORKFLOW_PNG
  } else if (entryBgUrl.value === ENTRY_BG_WORKFLOW_PNG) {
    entryBgUrl.value = ENTRY_BG_WORKFLOW_SVG
  }
}

const totalCount = computed(() => workspaceDesks.value.length)
const rosterCount = computed(() => ALL_PLANNED_YUANGON_PKG_IDS.value.size)
const visualizedEmployeeCount = computed(() =>
  showManagementLoopPanels.value ? Math.max(totalCount.value, rosterCount.value) : totalCount.value,
)
const enabledCount = computed(() => workspaceDesks.value.filter((d) => d.enabled).length)
const busyCount = computed(() => workspaceDesks.value.filter((d) => isBusy(d)).length)
const idleEnabledCount = computed(() => Math.max(0, enabledCount.value - busyCount.value))
const selectedDesk = computed(() => workspaceDesks.value.find((d) => d.empId === selectedEmpId.value) || null)

const loop = useLoopRuntimeConsole({
  plannedIds: ALL_PLANNED_YUANGON_PKG_IDS,
  visualizedEmployeeCount,
  totalCount,
  routeFocusedEmployeeId,
  showManagementLoopPanels,
})
const { panoramaLocation, dutyRosterLoopLocation, dutyRosterEmployeeLocation, loopParticipantRoleLabels } = loop

const { progressWidth, toggleDesk, processedShort, workShort, isLoopParticipant, deskLoopState, selectedDeskLoopState } =
  useWorkspaceDeskDisplay({
    nowMs,
    selectedDesk,
    loopRuntime: loop.loopRuntime,
    loopParticipantIds: loop.loopParticipantIds,
    loopParticipantRoleLabels: loop.loopParticipantRoleLabels,
  })
const entryKicker = computed(() => (showManagementLoopPanels.value ? '管理端可视化 · 六部门' : '企业版全景 · 四部门'))
const entryLead = computed(() =>
  showManagementLoopPanels.value
    ? `进入管理端六部门流程可视化，查看 ${rosterCount.value} 岗 AI 员工在编制图谱、流程派发和执行回写中的状态。`
    : '进入企业端四部门节点图，查看企业 Mod 栈下工具、执行、服务、管理工位与任务快照。',
)
const entryCtaText = computed(() => (showManagementLoopPanels.value ? '进入六部门可视化' : '进入企业全景'))

const workspaceStatSub = computed(() => {
  const label = enterpriseStack.value?.stackShortLabel
  return label ? `企业 Mod「${label}」栈内工位` : '企业 Mod 栈内工位'
})

onMounted(() => {
  if (showManagementLoopPanels.value) {
    // SSOT 派生：触发后端 /api/system/duty-roster 加载（失败时 composable 自动回退到构建时硬编码常量）
    void ensureDutyRosterLoaded()
  }
  void resolveEnterpriseModStack().then((stack) => {
    enterpriseStack.value = stack
  })
})
</script>

<template>
  <section class="ews" aria-labelledby="ews-heading" data-tour="employee-workspace-desks">
    <h3 id="ews-heading" class="ews-sr-only">员工工作流：入口与工位实况</h3>

    <router-link :to="panoramaLocation" class="ews-entry" role="link" :aria-label="entryCtaText">
      <div class="ews-entry-bg" aria-hidden="true">
        <img class="ews-entry-bg-img" :src="entryBgUrl" alt="" decoding="async" fetchpriority="low" @error="onEntryBgError" />
        <div class="ews-entry-vignette" />
      </div>
      <div class="ews-entry-ui">
        <p class="ews-entry-kicker">{{ entryKicker }}</p>
        <p class="ews-entry-lead">{{ entryLead }}</p>
        <div class="ews-entry-cta" aria-hidden="true">
          <span class="ews-entry-cta-arrow">→</span>
          <span class="ews-entry-cta-text">{{ entryCtaText }}</span>
        </div>
      </div>
    </router-link>

    <DutyRosterWorkflowLoopView v-if="showManagementLoopPanels" surface="employee-space" compact />
    <SelfEvolutionLoopRuntimePanel v-if="showManagementLoopPanels" surface="employee-space" compact />

    <EmployeeWorkspaceLoopConsole
      v-if="showManagementLoopPanels"
      :loop="loop"
      :route-focused-employee-id="routeFocusedEmployeeId"
      :route-focused-employee-in-workspace="routeFocusedEmployeeInWorkspace"
      :show-management-loop-panels="showManagementLoopPanels"
    />

    <div class="ews-stats" role="list" aria-label="员工工位概要">
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">{{ showManagementLoopPanels ? '编制工位' : '企业工位' }}</p>
        <p class="ews-stat-v">{{ visualizedEmployeeCount }}</p>
        <p class="ews-stat-sub">
          {{ showManagementLoopPanels ? `编制主索引 + ${workspaceStatSub}` : workspaceStatSub }}
        </p>
      </div>
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">已托管</p>
        <p class="ews-stat-v ews-stat-v--ok">{{ enabledCount }}</p>
        <p class="ews-stat-sub">副窗「一键托管」开</p>
      </div>
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">工作中</p>
        <p class="ews-stat-v ews-stat-v--busy">{{ busyCount }}</p>
        <p class="ews-stat-sub">最近活跃 · 视觉态忙</p>
      </div>
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">待命</p>
        <p class="ews-stat-v ews-stat-v--idle">{{ idleEnabledCount }}</p>
        <p class="ews-stat-sub">已托管但暂无忙态</p>
      </div>
    </div>

    <div id="ews-workflow-monitor" class="ews-monitor" role="region" aria-labelledby="ews-monitor-h" tabindex="-1">
      <div class="ews-monitor-head">
        <div>
          <h4 id="ews-monitor-h" class="ews-monitor-title">工位实况</h4>
          <p class="ews-monitor-desc">
            实时工位状态来自副窗「一键托管」开关与任务面板快照；左侧点工位卡片、右侧员工列表均可切换选中并与开关联动。
          </p>
        </div>
      </div>

      <div class="ews-layout">
        <div class="ews-grid" role="list" aria-label="工位卡片列表">
          <div v-if="!workspaceDesks.length" class="ews-empty" role="listitem">
            <p class="ews-empty-title">
              {{ showManagementLoopPanels ? '平台编制工位待同步' : '企业 Mod 工位待同步' }}
            </p>
            <p class="ews-empty-desc">
              <template v-if="showManagementLoopPanels">
                编制员工已经由图谱对齐为
                {{ rosterCount }} 岗；这里等待副窗托管或平台编制员工注册后显示实时工位卡片。
              </template>
              <template v-else>
                当前账号未同步到企业 Mod 员工工位；账号定制 Mod 开通并注册员工后，这里只显示本企业自己的工位卡片。
              </template>
            </p>
            <router-link :to="{ name: 'workflow-visualization' }" class="ews-empty-link">
              {{ showManagementLoopPanels ? '查看流程可视化' : '进入企业全景' }}
            </router-link>
          </div>
          <div
            v-for="row in workspaceDesks"
            :key="row.empId"
            class="ews-desk"
            :class="{
              'ews-desk--off': !row.enabled,
              'ews-desk--busy': isBusy(row),
              'ews-desk--loop': isLoopParticipant(row.empId),
              'ews-desk--selected': row.empId === selectedEmpId,
            }"
            role="listitem"
          >
            <button
              type="button"
              class="ews-desk-hit"
              :aria-current="row.empId === selectedEmpId ? 'true' : undefined"
              :aria-label="ariaLabel(row)"
              @click="selectDesk(row.empId)"
            >
              <span class="ews-desk-art" aria-hidden="true">
                <YuangongStation :enabled="row.enabled" :busy="isBusy(row)" :ariaLabel="ariaLabel(row)" />
                <span v-if="row.enabled" class="ews-desk-rpg" :class="{ 'ews-desk-rpg--busy': isBusy(row) }" aria-hidden="true">
                  <span class="ews-desk-rpg-row">
                    <span class="ews-desk-rpg-icon" aria-hidden="true">📄</span>
                    <span class="ews-desk-rpg-num">{{ processedShort(row) }}</span>
                  </span>
                  <span class="ews-desk-rpg-row">
                    <span class="ews-desk-rpg-icon" aria-hidden="true">⏱</span>
                    <span class="ews-desk-rpg-num">{{ workShort(row) }}</span>
                  </span>
                </span>
                <span v-if="isBusy(row)" class="ews-desk-pill ews-desk-pill--busy">忙</span>
                <span v-else-if="row.enabled" class="ews-desk-pill ews-desk-pill--idle">待命</span>
                <span v-else class="ews-desk-pill ews-desk-pill--off">未启</span>
              </span>

              <span class="ews-desk-meta">
                <span class="ews-desk-name" :title="row.panelTitle">{{ row.shortName }}</span>
                <span class="ews-desk-status">{{ statusLine(row) }}</span>
                <span v-if="showManagementLoopPanels && isLoopParticipant(row.empId)" class="ews-desk-loop-role">
                  {{ loopParticipantRoleLabels[row.empId] || 'Self-evolution Loop' }}
                </span>
                <span
                  v-if="showManagementLoopPanels"
                  class="ews-desk-loop-state"
                  :class="`ews-desk-loop-state--${deskLoopState(row).tone}`"
                >
                  {{ deskLoopState(row).label }}
                </span>
                <span class="ews-desk-progress" aria-hidden="true">
                  <span
                    class="ews-desk-progress-bar"
                    :class="{ 'ews-desk-progress-bar--busy': isBusy(row) }"
                    :style="{ width: progressWidth(row) }"
                  />
                </span>
              </span>
            </button>

            <button
              type="button"
              class="ews-desk-toggle"
              :class="{ 'ews-desk-toggle--on': row.enabled }"
              role="switch"
              :aria-checked="row.enabled"
              :aria-label="(row.enabled ? '关闭' : '开启') + '副窗托管：' + row.shortName"
              @click="toggleDesk(row.empId, $event)"
            >
              <span class="ews-desk-toggle-track" aria-hidden="true">
                <span class="ews-desk-toggle-thumb" />
              </span>
              <span class="ews-desk-toggle-label">{{ row.enabled ? '已开' : '已关' }}</span>
            </button>
          </div>
        </div>

        <div class="ews-side">
          <div v-if="showManagementLoopPanels && selectedDesk && selectedDeskLoopState" class="ews-selected-loop">
            <span>选中工位 Loop 上下文</span>
            <strong>{{ selectedDesk.shortName }}</strong>
            <p>{{ selectedDeskLoopState.detail }}</p>
            <div class="ews-selected-loop-actions">
              <router-link :to="dutyRosterEmployeeLocation(selectedDesk.empId)">去编制图谱定位</router-link>
              <router-link :to="dutyRosterLoopLocation">看完整 Loop</router-link>
            </div>
          </div>

          <WorkflowEmployeeInspector v-model:selected-emp-id="selectedEmpId" :desks="workspaceDesks" hide-workspace-link />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped src="./EmployeeWorkspaceScene.css"></style>
