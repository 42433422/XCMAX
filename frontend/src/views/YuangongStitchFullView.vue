<template>
  <div class="page-view panorama-view" id="view-yuangong-stitch-full">
    <div class="page-content panorama">
      <header class="panorama-head">
        <div class="panorama-head-row">
          <router-link :to="{ name: 'workflow-employee-space' }" class="panorama-btn">
            返回员工空间
          </router-link>
          <router-link :to="{ name: 'workflow-visualization' }" class="panorama-btn">
            流程全景说明
          </router-link>
        </div>
        <h2 class="panorama-title">员工工作流全景</h2>
        <p class="panorama-sub">
          左侧为四工位像素横向无缝拼接（无格缝），与右侧开关、快照一致。中键拖移、工具栏缩放。
        </p>
      </header>

      <div class="panorama-device" role="region" aria-label="员工工作流全景画框">
        <div class="panorama-body">
          <div class="panorama-stage">
            <StitchStage
              mode="composed"
              image-src=""
              :selected-emp-id="selectedEmpId"
              :hotspots="EMPTY_HOTSPOTS"
              :desks="desks"
              :resolve-station-aria-label="stationReaderLabel"
              @select="onSelectEmp"
            />
          </div>
          <div class="panorama-divider" aria-hidden="true" />
          <WorkflowEmployeeInspector
            v-model:selected-emp-id="selectedEmpId"
            :desks="desks"
            :pixel-skin="true"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import StitchStage from '@/components/workflow/StitchStage.vue'
import WorkflowEmployeeInspector from '@/components/workflow/WorkflowEmployeeInspector.vue'
import { useWorkflowEmployeeDesks } from '@/composables/useWorkflowEmployeeDesks'
import type { YuangongStitchHotspot } from '@/constants/yuangongStitchHotspots'

const EMPTY_HOTSPOTS: YuangongStitchHotspot[] = []

const { desks, ariaLabel } = useWorkflowEmployeeDesks()

const selectedEmpId = ref<string | null>(null)

function onSelectEmp(empId: string) {
  selectedEmpId.value = empId
}

function stationReaderLabel(empId: string): string {
  const row = desks.value.find((d) => d.empId === empId)
  return row ? ariaLabel(row) : `员工 ${empId}`
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

.panorama-view {
  background: radial-gradient(ellipse at top, #1e293b 0%, #0f172a 55%, #020617 100%);
}

.panorama {
  max-width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: min(calc(100dvh - 96px), 1200px);
}

.panorama-head {
  margin-bottom: 0;
}

.panorama-head-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}

.panorama-btn {
  display: inline-block;
  padding: 10px 12px;
  border: 3px solid #64748b;
  box-shadow: inset 0 -3px 0 rgba(0, 0, 0, 0.35), 3px 3px 0 rgba(0, 0, 0, 0.35);
  background: #334155;
  color: #f8fafc;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 7px;
  line-height: 1.6;
  letter-spacing: 0.03em;
  text-decoration: none;
  image-rendering: pixelated;
}

.panorama-btn:hover {
  background: #475569;
  color: #fff;
}

.panorama-title {
  margin: 0 0 8px;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.6;
  letter-spacing: 0.04em;
  color: #f1f5f9;
  text-shadow: 0 2px 0 rgba(0, 0, 0, 0.45);
}

.panorama-sub {
  margin: 0;
  font-size: 11px;
  line-height: 1.55;
  color: #94a3b8;
  max-width: 52rem;
}

.panorama-device {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border: 4px solid #475569;
  box-shadow:
    inset 0 0 0 2px #0f172a,
    6px 6px 0 rgba(0, 0, 0, 0.35);
  background: #0f172a;
}

.panorama-body {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 6px minmax(240px, 340px);
  gap: 0;
  align-items: stretch;
  min-height: min(calc(100dvh - 220px), 860px);
  min-width: 0;
}

@media (max-width: 960px) {
  .panorama-body {
    grid-template-columns: 1fr;
    grid-template-rows: auto 6px auto;
    min-height: 0;
  }

  .panorama-divider {
    min-height: 6px;
    width: 100% !important;
    background: repeating-linear-gradient(
      90deg,
      #334155 0,
      #334155 4px,
      #1e293b 4px,
      #1e293b 8px
    ) !important;
  }
}

.panorama-stage {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: 10px 8px 10px 10px;
}

.panorama-divider {
  width: 6px;
  background: repeating-linear-gradient(
    180deg,
    #334155 0,
    #334155 4px,
    #1e293b 4px,
    #1e293b 8px
  );
  box-shadow: inset 2px 0 0 #0f172a, inset -2px 0 0 #0f172a;
}

.panorama-body > :deep(.wfe-inspector--pixel) {
  margin: 10px 10px 10px 0;
  min-height: 0;
}

@media (max-width: 960px) {
  .panorama-body > :deep(.wfe-inspector--pixel) {
    margin: 0 10px 10px;
  }
}
</style>
