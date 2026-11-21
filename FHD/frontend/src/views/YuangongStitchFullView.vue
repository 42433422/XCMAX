<template>
  <div class="page-view" id="view-yuangong-stitch-full">
    <div class="page-content psf">
      <header class="psf-head">
        <div class="psf-head-row">
          <router-link :to="{ name: 'workflow-employee-space', query: { employee: selectedEmpId || undefined } }" class="psf-link-btn"> 返回员工空间 </router-link>
          <router-link :to="{ name: 'employee-workbench', query: { employee: selectedEmpId || undefined } }" class="psf-link-btn">员工工作台</router-link>
          <router-link v-if="showWorkflowPanoramaNav" :to="workflowVisualizationLocation" class="psf-link-btn psf-link-btn--ghost">
            流程全景说明
          </router-link>
        </div>
        <div class="psf-head-text">
          <h2 class="psf-title">员工图谱</h2>
          <p class="psf-sub">
            企业端<strong class="psf-sub-em">四部门节点图</strong>：{{ departmentNames }}。员工按当前账号可用目录和原有部门展示。
          </p>
          <p class="psf-sub" role="status">{{ syncState.stale ? '任务状态待核对，暂不显示为待命' : syncState.connected ? '任务状态实时同步' : '任务状态定时核对中' }}</p>
          <p v-if="registryError" class="psf-sub" role="alert">{{ registryError }} <button type="button" @click="refreshRegistry">重新同步员工目录</button></p>
        </div>
      </header>

      <div class="psf-stats" role="list" aria-label="工位概要">
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">总工位</p>
          <p class="psf-stat-v">{{ totalCount }}</p>
          <p class="psf-stat-sub">当前账号可用的 AI 员工</p>
        </div>
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">已托管</p>
          <p class="psf-stat-v psf-stat-v--ok">{{ enabledCount }}</p>
          <p class="psf-stat-sub">副窗「一键托管」开</p>
        </div>
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">工作中</p>
          <p class="psf-stat-v psf-stat-v--busy">{{ busyCount }}</p>
          <p class="psf-stat-sub">任务账本确认的运行状态</p>
        </div>
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">待命</p>
          <p class="psf-stat-v psf-stat-v--idle">{{ idleEnabledCount }}</p>
          <p class="psf-stat-sub">已托管且已核对无运行任务</p>
        </div>
      </div>

      <section class="psf-monitor" role="region" aria-labelledby="psf-monitor-h" :style="panoramaPaneStyle">
        <div class="psf-monitor-head">
          <div>
            <h3 id="psf-monitor-h" class="psf-monitor-title">四部门节点图</h3>
            <p class="psf-monitor-desc">
              四栏对应原有部门；员工与任务状态与工作空间、工作台同步。点击员工可查看详情，接入中断时保留上次状态并标记待核对。
            </p>
          </div>
        </div>

        <div class="psf-layout">
          <div class="psf-stage-wrap">
            <EnterpriseEstablishmentGraph
              :desks="panoramaDesks"
              :selected-emp-id="selectedEmpId"
              :is-busy="isBusy"
              @select="onSelectEmp"
            />
            <PaneResizeHandle
              v-if="isPanoramaPaneResizable"
              orientation="vertical"
              label="调整员工检查器宽度"
              @resize-start="onPanoramaPaneResizeStart"
              @reset="resetPanoramaPaneWidth"
            />
          </div>
          <WorkflowEmployeeInspector :selected-emp-id="selectedEmpId" :desks="panoramaDesks" hide-workspace-link @update:selected-emp-id="onSelectEmp" />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import { useResizablePane } from '@/composables/useResizablePane'
import EnterpriseEstablishmentGraph from '@/components/workflow/EnterpriseEstablishmentGraph.vue'
import WorkflowEmployeeInspector from '@/components/workflow/WorkflowEmployeeInspector.vue'
import { useWorkflowEmployeeDesks, type WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import { resolveWorkflowVisualizationLocation } from '@/utils/workflowNav'
import { useWorkflowPanoramaNavVisible } from '@/composables/useWorkflowPanoramaNavVisible'
import { isCustomPhaseEmployeeCarrierModId } from '@/utils/modWorkflowEmployees'
import { ENTERPRISE_ORG_LAYERS } from '@/constants/enterpriseWorkflowEstablishment'
import { useWorkspaceDeskSelection } from '@/composables/useWorkspaceDeskSelection'
import { useWorkflowEmployeeRegistrySync } from '@/composables/useWorkflowEmployeeRegistrySync'

const workflowVisualizationLocation = resolveWorkflowVisualizationLocation()
const { showWorkflowPanoramaNav } = useWorkflowPanoramaNavVisible()
const PANORAMA_LAYOUT_MQ = '(max-width: 960px)'

const departmentNames = ENTERPRISE_ORG_LAYERS.map(department => department.label).join('、')

const { error: registryError, refresh: refreshRegistry } = useWorkflowEmployeeRegistrySync()
const { desks, isBusy, syncState } = useWorkflowEmployeeDesks()
// The backend directory enforces account/manifest visibility; use the same rows as the office.
const panoramaDesks = computed<WorkflowEmployeeDeskRow[]>(() => desks.value
  .filter(row => !isCustomPhaseEmployeeCarrierModId(row.carrierModId || row.hostModId)))

const { selectedEmpId, selectDesk } = useWorkspaceDeskSelection(panoramaDesks)

const totalCount = computed(() => panoramaDesks.value.length)
const enabledCount = computed(() => panoramaDesks.value.filter((d) => d.enabled).length)
const busyCount = computed(() => panoramaDesks.value.filter((d) => isBusy(d)).length)
const idleEnabledCount = computed(() => panoramaDesks.value.filter(d => d.enabled
  && d.snapshot?.authority === 'task-center' && !d.snapshot.stale
  && ['idle', 'done'].includes(d.snapshot.officeState || '')).length)

const isPanoramaPaneResizable = ref(true)
let panoramaPaneViewportMedia: MediaQueryList | null = null

const {
  paneStyle: panoramaPaneStyle,
  startResize: onPanoramaPaneResizeStart,
  resetSize: resetPanoramaPaneWidth,
  stopResize: stopPanoramaPaneResize,
} = useResizablePane({
  paneKey: 'workflow.panorama-inspector',
  cssVarName: '--psf-inspector-width',
  orientation: 'vertical',
  invertDelta: true,
  defaultSize: 300,
  minSize: 240,
  maxSize: 420,
  enabled: () => isPanoramaPaneResizable.value,
})

function onSelectEmp(empId: string | null) {
  selectDesk(empId)
}

function onPanoramaPaneViewportChange(event: MediaQueryList | MediaQueryListEvent): void {
  isPanoramaPaneResizable.value = !event.matches
  if (!isPanoramaPaneResizable.value) {
    stopPanoramaPaneResize()
  }
}

onMounted(() => {
  panoramaPaneViewportMedia = window.matchMedia(PANORAMA_LAYOUT_MQ)
  onPanoramaPaneViewportChange(panoramaPaneViewportMedia)
  if (typeof panoramaPaneViewportMedia.addEventListener === 'function') {
    panoramaPaneViewportMedia.addEventListener('change', onPanoramaPaneViewportChange)
  } else if (typeof panoramaPaneViewportMedia.addListener === 'function') {
    panoramaPaneViewportMedia.addListener(onPanoramaPaneViewportChange)
  }
})

onBeforeUnmount(() => {
  stopPanoramaPaneResize()
  if (!panoramaPaneViewportMedia) return
  if (typeof panoramaPaneViewportMedia.removeEventListener === 'function') {
    panoramaPaneViewportMedia.removeEventListener('change', onPanoramaPaneViewportChange)
  } else if (typeof panoramaPaneViewportMedia.removeListener === 'function') {
    panoramaPaneViewportMedia.removeListener(onPanoramaPaneViewportChange)
  }
})
</script>

<style scoped>
.psf {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: min(calc(100dvh - 96px), 1200px);
  --psf-inspector-width: 300px;
}

.psf-head-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.psf-link-btn {
  display: inline-flex;
  align-items: center;
  padding: 7px 12px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  background: #fff;
  color: #374151;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}

.psf-link-btn:hover {
  background: #f3f4f6;
  border-color: #cbd5e1;
  color: #111827;
}

.psf-link-btn--ghost {
  background: transparent;
  border-color: #e5e7eb;
  color: #6b7280;
}

.psf-link-btn--ghost:hover {
  background: #f9fafb;
  color: #374151;
}

.psf-title {
  margin: 0 0 6px;
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.psf-sub {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: #64748b;
  max-width: 56rem;
}

.psf-sub-em {
  font-weight: 700;
  color: #334155;
  font-style: normal;
}

.psf-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 880px) {
  .psf-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.psf-stat {
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: #fff;
}

.psf-stat-k {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.psf-stat-v {
  margin: 4px 0 2px;
  font-size: 1.5rem;
  font-weight: 700;
  line-height: 1.2;
  color: #111827;
  font-variant-numeric: tabular-nums;
}

.psf-stat-v--ok {
  color: #059669;
}

.psf-stat-v--busy {
  color: #2563eb;
}

.psf-stat-v--idle {
  color: #7c3aed;
}

.psf-stat-sub {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: #9ca3af;
}

.psf-monitor {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 14px 14px 16px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: linear-gradient(180deg, #f9fafb 0%, #fff 55%);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
}

.psf-monitor-head {
  margin-bottom: 12px;
}

.psf-monitor-title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.psf-monitor-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #6b7280;
  max-width: 56rem;
}

.psf-layout {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--psf-inspector-width);
  gap: 14px;
  align-items: stretch;
  min-height: min(calc(100dvh - 320px), 720px);
  min-width: 0;
}

@media (max-width: 960px) {
  .psf-layout {
    grid-template-columns: 1fr;
    min-height: 0;
  }
}

.psf-stage-wrap {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
}

.psf-layout > :deep(.wfe-inspector) {
  min-height: 0;
  max-height: none;
}

.psf-layout > :deep(.wfe-inspector-list) {
  max-height: min(58vh, 640px);
}

@media (max-width: 960px) {
  .psf-layout > :deep(.wfe-inspector-list) {
    max-height: min(42vh, 480px);
  }
}
</style>
