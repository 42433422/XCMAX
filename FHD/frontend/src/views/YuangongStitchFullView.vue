<template>
  <div class="page-view" id="view-yuangong-stitch-full">
    <div class="page-content psf">
      <header class="psf-head">
        <div class="psf-head-row">
          <router-link :to="{ name: 'workflow-employee-space' }" class="psf-link-btn">
            返回员工空间
          </router-link>
          <router-link
            v-if="showWorkflowPanoramaNav"
            :to="workflowVisualizationLocation"
            class="psf-link-btn psf-link-btn--ghost"
          >
            流程全景说明
          </router-link>
        </div>
        <div class="psf-head-text">
          <h2 class="psf-title">员工工作流全景</h2>
          <p class="psf-sub">
            企业端<strong class="psf-sub-em">四部门节点图</strong>：员工归属「行业通用 + 定制」组成的企业 Mod，上岗后进入该栈下的工具 / 执行 / 服务 / 管理四部门。
          </p>
        </div>
      </header>

      <div class="psf-stats" role="list" aria-label="工位概要">
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">总工位</p>
          <p class="psf-stat-v">{{ totalCount }}</p>
          <p class="psf-stat-sub">已上岗 AI 员工（企业 Mod 栈内）</p>
        </div>
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">已托管</p>
          <p class="psf-stat-v psf-stat-v--ok">{{ enabledCount }}</p>
          <p class="psf-stat-sub">副窗「一键托管」开</p>
        </div>
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">工作中</p>
          <p class="psf-stat-v psf-stat-v--busy">{{ busyCount }}</p>
          <p class="psf-stat-sub">最近活跃 · 视觉忙态</p>
        </div>
        <div class="psf-stat" role="listitem">
          <p class="psf-stat-k">待命</p>
          <p class="psf-stat-v psf-stat-v--idle">{{ idleEnabledCount }}</p>
          <p class="psf-stat-sub">已托管但暂无忙态</p>
        </div>
      </div>

      <section
        class="psf-monitor"
        role="region"
        aria-labelledby="psf-monitor-h"
        :style="panoramaPaneStyle"
      >
        <div class="psf-monitor-head">
          <div>
            <h3 id="psf-monitor-h" class="psf-monitor-title">四部门节点图</h3>
            <p class="psf-monitor-desc">
              四栏为四部门；横幅展示当前企业 Mod（行业包 + 定制 Mod）。AI 市场安装的员工自动挂靠该栈并上岗。绿点=已托管、蓝点=忙。
            </p>
          </div>
        </div>

        <div class="psf-layout">
          <div class="psf-stage-wrap">
            <EnterpriseEstablishmentGraph
              :desks="panoramaDesks"
              :selected-emp-id="selectedEmpId"
              :is-busy="isBusy"
              :enterprise-stack-label="enterpriseStackLabel"
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
          <WorkflowEmployeeInspector
            v-model:selected-emp-id="selectedEmpId"
            :desks="panoramaDesks"
            hide-workspace-link
          />
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import PaneResizeHandle from '@/components/PaneResizeHandle.vue'
import { useResizablePane } from '@/composables/useResizablePane'
import EnterpriseEstablishmentGraph from '@/components/workflow/EnterpriseEstablishmentGraph.vue'
import WorkflowEmployeeInspector from '@/components/workflow/WorkflowEmployeeInspector.vue'
import {
  useWorkflowEmployeeDesks,
  type WorkflowEmployeeDeskRow,
} from '@/composables/useWorkflowEmployeeDesks'
import { resolveWorkflowVisualizationLocation } from '@/utils/workflowNav'
import { useWorkflowPanoramaNavVisible } from '@/composables/useWorkflowPanoramaNavVisible'
import {
  employeeBelongsToEnterpriseStack,
  isWorkflowCarrierModId,
  type EnterpriseModStack,
} from '@/constants/enterpriseModStack'
import { isHostBridgeModId } from '@/constants/genericModPack'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'

const workflowVisualizationLocation = resolveWorkflowVisualizationLocation()
const { showWorkflowPanoramaNav } = useWorkflowPanoramaNavVisible()
const PANORAMA_LAYOUT_MQ = '(max-width: 960px)'

const enterpriseStack = ref<EnterpriseModStack | null>(null)
const enterpriseStackLabel = computed(() => enterpriseStack.value?.stackLabel || '')

const { desks, isBusy } = useWorkflowEmployeeDesks()

const panoramaDesks = computed<WorkflowEmployeeDeskRow[]>(() => {
  const stack = enterpriseStack.value
  return desks.value.filter((d) => {
    const host = d.hostModId
    if (!host) return false
    if (stack) return employeeBelongsToEnterpriseStack(host, stack)
    return isWorkflowCarrierModId(host) || isHostBridgeModId(host)
  })
})

const selectedEmpId = ref<string | null>(null)

const totalCount = computed(() => panoramaDesks.value.length)
const enabledCount = computed(() => panoramaDesks.value.filter((d) => d.enabled).length)
const busyCount = computed(() => panoramaDesks.value.filter((d) => isBusy(d)).length)
const idleEnabledCount = computed(() => Math.max(0, enabledCount.value - busyCount.value))

watch(
  () => panoramaDesks.value.map((d) => d.empId).join('\0'),
  () => {
    const list = panoramaDesks.value
    if (!list.length) {
      selectedEmpId.value = null
      return
    }
    const cur = selectedEmpId.value
    if (!cur || !list.some((d) => d.empId === cur)) {
      selectedEmpId.value = list[0].empId
    }
  },
  { immediate: true },
)

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

function onSelectEmp(empId: string) {
  selectedEmpId.value = empId
}

function onPanoramaPaneViewportChange(event: MediaQueryList | MediaQueryListEvent): void {
  isPanoramaPaneResizable.value = !event.matches
  if (!isPanoramaPaneResizable.value) {
    stopPanoramaPaneResize()
  }
}

onMounted(() => {
  void resolveEnterpriseModStack().then((stack) => {
    enterpriseStack.value = stack
  })
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
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
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
