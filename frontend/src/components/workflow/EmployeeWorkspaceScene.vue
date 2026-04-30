<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useWorkflowEmployeeDesks } from '@/composables/useWorkflowEmployeeDesks'
import YuangongStation from '@/components/workflow/YuangongStation.vue'
import YuangongInteractiveWorkstation from '@/components/workflow/YuangongInteractiveWorkstation.vue'
import {
  YUANGONG_ENTRY_STITCH_PNG,
  YUANGONG_ENTRY_WORKFLOW_PNG,
  YUANGONG_ENTRY_WORKFLOW_SVG,
} from '@/constants/yuangongAssets'

/** 入口横幅：优先 yuangong 员工拼接图，再回退 workflow 占位 */
const ENTRY_BG_STITCH = YUANGONG_ENTRY_STITCH_PNG
const ENTRY_BG_WORKFLOW_PNG = YUANGONG_ENTRY_WORKFLOW_PNG
const ENTRY_BG_WORKFLOW_SVG = YUANGONG_ENTRY_WORKFLOW_SVG

const { desks, statusLine, ariaLabel, isBusy } = useWorkflowEmployeeDesks()

/** 与示意图联动的工位：点击卡片切换；默认同列表首项 */
const schematicEmpId = ref<string | null>(null)

watch(
  () => desks.value.map((d) => d.empId).join('\0'),
  () => {
    const list = desks.value
    if (!list.length) {
      schematicEmpId.value = null
      return
    }
    const cur = schematicEmpId.value
    if (!cur || !list.some((d) => d.empId === cur)) {
      schematicEmpId.value = list[0].empId
    }
  },
  { immediate: true }
)

const schematicRow = computed(() => {
  const id = schematicEmpId.value
  if (!id) return null
  return desks.value.find((d) => d.empId === id) ?? null
})

function selectSchematicDesk(empId: string) {
  schematicEmpId.value = empId
}

const entryBgUrl = ref(ENTRY_BG_STITCH)

function onEntryBgError() {
  if (entryBgUrl.value === ENTRY_BG_STITCH) {
    entryBgUrl.value = ENTRY_BG_WORKFLOW_PNG
  } else if (entryBgUrl.value === ENTRY_BG_WORKFLOW_PNG) {
    entryBgUrl.value = ENTRY_BG_WORKFLOW_SVG
  }
}

</script>

<template>
  <section class="ews" aria-labelledby="ews-heading">
    <h3 id="ews-heading" class="ews-sr-only">员工工作流：入口与工位实况</h3>

    <div
      class="ews-entry"
      role="banner"
      aria-label="员工空间入口；背景图可进入员工工作流全景页，实况请在下方查看"
    >
      <div class="ews-entry-bg">
        <router-link
          :to="{ name: 'workflow-employee-stitch-full' }"
          class="ews-entry-bg-hit"
          aria-label="进入员工工作流全景页面"
        >
          <img
            class="ews-entry-bg-img"
            :src="entryBgUrl"
            alt=""
            decoding="async"
            fetchpriority="low"
            @error="onEntryBgError"
          />
        </router-link>
        <div class="ews-entry-vignette" aria-hidden="true" />
        <p class="ews-entry-bg-hint" aria-hidden="true">点击进入全景</p>
      </div>
      <div class="ews-entry-ui">
        <p class="ews-entry-kicker">工作流员工</p>
        <p class="ews-entry-title">员工空间</p>
        <p class="ews-entry-lead">
          下方为实时工位状态；此处仅为入口画面。背景图可进入工作流全景页。
        </p>
      </div>
    </div>

    <div
      id="ews-workflow-monitor"
      class="ews-monitor"
      role="region"
      aria-labelledby="ews-monitor-h"
      tabindex="-1"
    >
      <h4 id="ews-monitor-h" class="ews-monitor-title">工位实况</h4>
      <p class="ews-monitor-desc">
        工位层与员工层来自 public/yuangong；未启用副窗仅工位。标签样式可在全局覆盖 .ews-label-slot。
        点击某一工位卡片，可在上方示意图顶/底同步该工位的状态与工作流全称。
      </p>

      <YuangongInteractiveWorkstation
        :status-line="schematicRow ? statusLine(schematicRow) : '暂无工位'"
        :workflow-full-name="schematicRow?.panelTitle ?? '—'"
      />

      <div class="ews-grid" role="list">
        <div
          v-for="row in desks"
          :key="row.empId"
          class="ews-desk"
          :class="{
            'ews-desk--off': !row.enabled,
            'ews-desk--busy': isBusy(row),
            'ews-desk--schematic': row.empId === schematicEmpId,
          }"
          role="listitem"
          tabindex="0"
          :title="
            row.empId === schematicEmpId
              ? '当前示意图对应该工位'
              : '点击后在上方示意图中显示该工位状态与工作流全称'
          "
          @click="selectSchematicDesk(row.empId)"
          @keydown.enter.prevent="selectSchematicDesk(row.empId)"
          @keydown.space.prevent="selectSchematicDesk(row.empId)"
        >
          <div class="ews-label-slot" data-yuangong-label :data-emp-id="row.empId">
            <p class="ews-label-slot__name" :title="row.panelTitle">{{ row.shortName }}</p>
            <p class="ews-label-slot__status">{{ statusLine(row) }}</p>
          </div>

          <YuangongStation
            :enabled="row.enabled"
            :busy="isBusy(row)"
            :ariaLabel="ariaLabel(row)"
          />
        </div>
      </div>
    </div>

    <p class="ews-foot">
      yuangong 分层：<code>frontend/public/yuangong/</code>（desk / staff / staff-busy / <code>员工.png</code> 热点示意）。
      入口横幅拼接图：<code>stitch-tutorial.png</code>（点击进入
      <code>/workflow-employee-space/stitch-full</code> 工作流全景）；缺失时回退
      <code>workflow/employee-space-bg</code>。
    </p>
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
  margin-top: 0;
}

.ews-entry {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  min-height: min(240px, 36vh);
  border: 1px solid #e5e7eb;
  background: #0f172a;
}

.ews-entry-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.ews-entry-bg-hit {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  cursor: pointer;
  background: transparent;
  text-align: left;
  color: inherit;
  text-decoration: none;
}

.ews-entry-bg-hit:focus {
  outline: none;
}

.ews-entry-bg-hit:focus-visible {
  outline: 2px solid #fff;
  outline-offset: -2px;
}

.ews-entry-bg-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center bottom;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  pointer-events: none;
  display: block;
}

.ews-entry-bg-hint {
  position: absolute;
  right: 14px;
  bottom: 12px;
  z-index: 2;
  margin: 0;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(255, 255, 255, 0.95);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
  background: rgba(15, 23, 42, 0.42);
  pointer-events: none;
}

.ews-entry-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    rgba(15, 23, 42, 0.15) 0%,
    rgba(15, 23, 42, 0.05) 45%,
    rgba(15, 23, 42, 0.45) 100%
  );
}

.ews-entry-ui {
  position: relative;
  z-index: 1;
  min-height: min(240px, 36vh);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 10px;
  padding: 20px 22px;
  max-width: 28rem;
}

.ews-entry-kicker {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.88);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}

.ews-entry-title {
  margin: 0;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 14px;
  line-height: 1.5;
  letter-spacing: 0.04em;
  color: #fff;
  text-shadow: 0 2px 0 rgba(0, 0, 0, 0.35);
}

.ews-entry-lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: rgba(255, 255, 255, 0.9);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}

.ews-monitor {
  margin-top: 14px;
  padding: 14px 14px 16px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: linear-gradient(180deg, #f9fafb 0%, #fff 50%);
  outline: none;
}

.ews-monitor-title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.ews-monitor-desc {
  margin: 0 0 12px;
  font-size: 12px;
  line-height: 1.5;
  color: #6b7280;
}

.ews-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.ews-desk {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  padding: 10px 10px 8px;
  min-height: 168px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.ews-desk--off {
  opacity: 0.58;
  filter: grayscale(0.25);
}

.ews-desk--busy {
  box-shadow: 0 0 0 1px #93c5fd inset;
}

.ews-desk--schematic {
  outline: 2px solid #2563eb;
  outline-offset: 1px;
}

.ews-desk[tabindex='0']:focus-visible {
  outline: 2px solid #1d4ed8;
  outline-offset: 2px;
}

.ews-foot {
  margin: 10px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: #6b7280;
}

.ews-foot code {
  font-size: 11px;
  word-break: break-all;
}
</style>
