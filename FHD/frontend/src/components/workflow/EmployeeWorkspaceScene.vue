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

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

.ews-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.ews {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 0;
}

/* —— 入口横幅 —— */
.ews-entry {
  position: relative;
  display: block;
  border-radius: 12px;
  overflow: hidden;
  min-height: 180px;
  border: 1px solid #e5e7eb;
  background: #0f172a;
  text-decoration: none;
  color: inherit;
  isolation: isolate;
  transition:
    transform 0.2s ease,
    box-shadow 0.2s ease;
}

.ews-entry:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.18);
}

.ews-entry:focus {
  outline: none;
}

.ews-entry:focus-visible {
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.45);
}

.ews-entry-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.ews-entry-bg-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center bottom;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  display: block;
}

.ews-entry-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(90deg, rgba(15, 23, 42, 0.78) 0%, rgba(15, 23, 42, 0.32) 45%, rgba(15, 23, 42, 0.05) 100%),
    linear-gradient(180deg, rgba(15, 23, 42, 0.05) 0%, rgba(15, 23, 42, 0.55) 100%);
}

.ews-entry-ui {
  position: relative;
  z-index: 1;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 10px;
  padding: 20px 24px;
  max-width: 32rem;
}

.ews-entry-kicker {
  margin: 0;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 10px;
  line-height: 1.5;
  letter-spacing: 0.08em;
  color: #93c5fd;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55);
}

.ews-entry-lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
}

.ews-entry-cta {
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.92);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.35);
}

.ews-entry-cta-arrow {
  font-size: 14px;
  transition: transform 0.2s ease;
}

.ews-entry:hover .ews-entry-cta-arrow {
  transform: translateX(3px);
}

.ews-empty-link {
  flex: 0 0 auto;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  padding: 8px 10px;
  text-decoration: none;
}

.ews-empty-link:hover {
  background: #dbeafe;
}

/* —— 概要数据条 —— */
.ews-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.ews-stat {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ews-stat-k {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: 0.04em;
}

.ews-stat-v {
  margin: 0;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 22px;
  line-height: 1.3;
  color: #111827;
  font-variant-numeric: tabular-nums;
}

.ews-stat-v--ok {
  color: #059669;
}

.ews-stat-v--busy {
  color: #2563eb;
}

.ews-stat-v--idle {
  color: #7c3aed;
}

.ews-stat-sub {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: #9ca3af;
}

/* —— 工位实况 —— */
.ews-monitor {
  padding: 14px 14px 16px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: linear-gradient(180deg, #f9fafb 0%, #fff 50%);
  outline: none;
}

.ews-monitor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.ews-monitor-title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.ews-monitor-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #6b7280;
  max-width: 56rem;
}

.ews-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  gap: 14px;
  align-items: start;
}

@media (max-width: 880px) {
  .ews-layout {
    grid-template-columns: 1fr;
  }
}

.ews-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.ews-empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 180px;
  border: 1px dashed #bfdbfe;
  border-radius: 12px;
  background: #eff6ff;
  padding: 18px;
  justify-content: center;
}

.ews-empty-title {
  margin: 0;
  color: #1e3a8a;
  font-size: 14px;
  font-weight: 800;
}

.ews-empty-desc {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.ews-empty-link {
  align-self: flex-start;
  background: #fff;
}

.ews-desk {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    border-color 0.15s ease;
}

.ews-desk:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
  border-color: #cbd5e1;
}

.ews-desk--off {
  background: #f9fafb;
}

.ews-desk--off .ews-desk-art {
  filter: grayscale(0.35);
  opacity: 0.85;
}

.ews-desk--busy {
  border-color: #93c5fd;
  background: linear-gradient(180deg, #f5faff 0%, #ffffff 60%);
}

.ews-desk--selected {
  border-color: #2563eb;
  box-shadow:
    0 0 0 1px #93c5fd inset,
    0 8px 24px rgba(37, 99, 235, 0.18);
}

.ews-desk-hit {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  padding: 10px 12px 10px;
  margin: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
}

.ews-desk-hit:focus {
  outline: none;
}

.ews-desk-hit:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
  border-radius: 10px;
}

.ews-desk-art {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 10px;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 50% 90%, rgba(37, 99, 235, 0.08) 0%, transparent 65%), linear-gradient(180deg, #eef2ff 0%, #ffffff 75%);
  display: block;
  border: 1px solid #e5e7eb;
}

.ews-desk-art :deep(.yuangong-stack) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.ews-desk-art :deep(.yuangong-desk) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center bottom;
  max-width: none;
  max-height: none;
}

.ews-desk-art :deep(.yuangong-staff) {
  position: absolute;
  inset: 0;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center bottom;
  max-width: none;
  max-height: none;
}

/* —— RPG 风格量化数据：员工头顶悬浮的「已处理 / 在岗工时」 —— */
.ews-desk-rpg {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 6px;
  border-radius: 4px;
  background: rgba(11, 17, 32, 0.78);
  box-shadow:
    inset 0 0 0 1px rgba(56, 189, 248, 0.45),
    0 1px 0 rgba(0, 0, 0, 0.45);
  color: #f1f5f9;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 8px;
  line-height: 1.3;
  letter-spacing: 0.03em;
  pointer-events: none;
  image-rendering: pixelated;
}

.ews-desk-rpg--busy {
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.85),
    0 0 0 2px rgba(96, 165, 250, 0.18),
    0 1px 0 rgba(0, 0, 0, 0.45);
}

.ews-desk-rpg-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ews-desk-rpg-icon {
  font-size: 10px;
  line-height: 1;
}

.ews-desk-rpg-num {
  color: #7dd3fc;
  font-variant-numeric: tabular-nums;
}

.ews-desk-pill {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 2;
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #fff;
  background: rgba(15, 23, 42, 0.55);
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.4);
}

.ews-desk-pill--busy {
  background: linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%);
}

.ews-desk-pill--idle {
  background: linear-gradient(180deg, #7c3aed 0%, #6d28d9 100%);
}

.ews-desk-pill--off {
  background: rgba(107, 114, 128, 0.85);
}

.ews-desk-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ews-desk-name {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ews-desk-status {
  display: -webkit-box;
  font-size: 12px;
  line-height: 1.45;
  color: #6b7280;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.9em;
}

.ews-desk-progress {
  display: block;
  width: 100%;
  height: 5px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
  margin-top: 2px;
}

.ews-desk-progress-bar {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #cbd5e1 0%, #94a3b8 100%);
  transition: width 0.25s ease;
}

.ews-desk-progress-bar--busy {
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%);
}

.ews-desk-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  margin: 0 12px 12px;
  padding: 4px 10px 4px 4px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #f9fafb;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  cursor: pointer;
  user-select: none;
  text-align: left;
}

.ews-desk-toggle:focus {
  outline: none;
}

.ews-desk-toggle:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 2px;
}

.ews-desk-toggle--on {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}

.ews-desk-toggle-track {
  position: relative;
  width: 26px;
  height: 14px;
  border-radius: 999px;
  background: #cbd5e1;
  display: inline-block;
  transition: background 0.2s ease;
}

.ews-desk-toggle--on .ews-desk-toggle-track {
  background: #2563eb;
}

.ews-desk-toggle-thumb {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.2s ease;
}

.ews-desk-toggle--on .ews-desk-toggle-thumb {
  transform: translateX(12px);
}

.ews-desk-toggle-label {
  font-variant-numeric: tabular-nums;
}

.ews-desk-loop-role {
  overflow: hidden;
  max-width: 100%;
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 999px;
  background: #ccfbf1;
  color: #115e59;
  font-size: 10px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-desk-loop-state {
  overflow: hidden;
  max-width: 100%;
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 10px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-desk-loop-state--run {
  background: #dcfce7;
  color: #166534;
}

.ews-desk-loop-state--idle {
  background: #eff6ff;
  color: #1d4ed8;
}

.ews-desk-loop-state--warn {
  background: #fffbeb;
  color: #92400e;
}

.ews-desk-loop-state--off {
  background: #f1f5f9;
  color: #64748b;
}

.ews-side {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.ews-selected-loop {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 12px;
  border: 1px solid rgba(20, 184, 166, 0.18);
  border-radius: 12px;
  background: radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.12), transparent 36%), #ffffff;
}

.ews-selected-loop span {
  color: #0f766e;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

.ews-selected-loop strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 900;
}

.ews-selected-loop p {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.ews-selected-loop-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 3px;
}

.ews-selected-loop-actions a {
  padding: 5px 8px;
  border-radius: 999px;
  background: #f0fdfa;
  color: #0f766e;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.ews-desk--loop {
  position: relative;
  border-color: #14b8a6;
  box-shadow:
    0 0 0 2px rgba(20, 184, 166, 0.18),
    0 10px 28px rgba(15, 118, 110, 0.13);
}

.ews-desk--loop::after {
  content: 'LOOP';
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  padding: 3px 6px;
  border-radius: 999px;
  background: #0f766e;
  color: #ecfeff;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.04em;
}
</style>
