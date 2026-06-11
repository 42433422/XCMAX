<template>
  <div class="workflow-employee-section">
    <div class="workflow-employee-section-head">
      <div class="workflow-employee-heading">{{ heading }}</div>
      <router-link
        v-if="effectiveShowPanoramaLink"
        :to="workflowVisualizationLocation"
        class="workflow-employee-visual-link"
        :title="workflowPanoramaLinkTitle"
      >流程全景</router-link>
    </div>

    <p v-if="statusHint" class="workflow-employee-hint">{{ statusHint }}</p>
    <div
      v-else
      class="workflow-employee-list"
      role="group"
      aria-label="工作流 AI 员工"
    >
      <button
        v-for="emp in workflowEmployeeDefs"
        :key="emp.id"
        type="button"
        class="workflow-employee-row"
        :aria-pressed="workflowEmployeesEnabled[emp.id] ? 'true' : 'false'"
        @click="toggleWorkflowEmployee(emp.id)"
      >
        <span class="workflow-employee-label">{{ emp.label }}</span>
        <div
          class="toggle-switch workflow-employee-toggle"
          :class="{ active: workflowEmployeesEnabled[emp.id] }"
        >
          <div class="toggle-slider"></div>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { useWorkflowModsRuntimeContext } from '@/composables/useWorkflowModsRuntimeContext'
import { useWorkflowEmployeeRegistrySync } from '@/composables/useWorkflowEmployeeRegistrySync'
import { resolveLabel } from '@/utils/workflowEmployeeRegistry'
import { resolveWorkflowVisualizationLocation } from '@/utils/workflowNav'

import { resolveWorkflowVisualizationLocation } from '@/utils/workflowNav'
import { useWorkflowPanoramaNavVisible } from '@/composables/useWorkflowPanoramaNavVisible'

const props = withDefaults(
  defineProps<{
    heading?: string
    showPanoramaLink?: boolean
  }>(),
  {
    heading: '工作流员工选择',
  },
)

const { showWorkflowPanoramaNav } = useWorkflowPanoramaNavVisible()
const effectiveShowPanoramaLink = computed(
  () => props.showPanoramaLink ?? showWorkflowPanoramaNav.value,
)

const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()
useWorkflowEmployeeRegistrySync()
const { ctx, modWorkflowEmployeesActive } = useWorkflowModsRuntimeContext()
const {
  enabled: workflowEmployeesEnabled,
  registryEntries,
  registryLoaded,
} = storeToRefs(workflowAiEmployeesStore)

const workflowVisualizationLocation = resolveWorkflowVisualizationLocation()

const workflowPanoramaLinkTitle = computed(() =>
  modWorkflowEmployeesActive.value
    ? '查看已安装工作流员工的执行逻辑与过程'
    : '查看工作流执行逻辑与过程',
)

const workflowEmployeeDefs = computed(() =>
  registryEntries.value.map((entry) => ({
    id: entry.id,
    label: resolveLabel(entry, (key) => key),
  })),
)

const statusHint = computed(() => {
  if (ctx.value.clientModsUiOff) {
    return '当前为原版模式（前端不加载扩展）：请关闭原版模式并从 MOD 商店安装工作流员工 Mod 后刷新。'
  }
  if (ctx.value.modsDisabledByServer) {
    return '后端已关闭扩展（XCAGI_DISABLE_MODS）：无法展示工作流员工。'
  }
  if (!ctx.value.isModsListLoaded) {
    return '正在与后端同步扩展列表…'
  }
  if (!registryLoaded.value) {
    return '正在加载工作流员工注册表…'
  }
  if (!workflowEmployeeDefs.value.length) {
    return '当前未加载任何工作流员工 Mod。请从员工商店安装后刷新。'
  }
  return ''
})

function toggleWorkflowEmployee(id: string) {
  workflowAiEmployeesStore.toggle(id)
}
</script>

<style scoped>
.workflow-employee-section {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 10px 10px 8px;
  background: #fff;
}
.workflow-employee-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}
.workflow-employee-heading {
  font-size: 13px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 0;
  flex: 1;
  min-width: 0;
}
.workflow-employee-visual-link {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: #2563eb;
  text-decoration: none;
  padding: 4px 9px;
  border-radius: 6px;
  border: 1px solid #bfdbfe;
  background: #eff6ff;
  line-height: 1.2;
  white-space: nowrap;
}
.workflow-employee-visual-link:hover {
  background: #dbeafe;
  color: #1d4ed8;
}
.workflow-employee-hint {
  margin: 0;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
}
.workflow-employee-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.workflow-employee-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  text-align: left;
  padding: 8px 10px;
  border: 1px solid #eef2f7;
  border-radius: 8px;
  background: #f9fafb;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.workflow-employee-row:hover {
  background: #f3f4f6;
  border-color: #e5e7eb;
}
.workflow-employee-label {
  font-size: 12px;
  font-weight: 500;
  color: #1f2937;
  line-height: 1.35;
  flex: 1;
  min-width: 0;
}
.workflow-employee-toggle.toggle-switch {
  flex-shrink: 0;
  width: 40px;
  height: 20px;
  background: #d1d5db;
  border-radius: 10px;
  position: relative;
  transition: background 0.3s;
  pointer-events: none;
}
.workflow-employee-toggle.toggle-switch.active {
  background: #4a90d9;
}
.workflow-employee-toggle .toggle-slider {
  width: 16px;
  height: 16px;
  background: #fff;
  border-radius: 50%;
  position: absolute;
  top: 2px;
  left: 2px;
  transition: transform 0.3s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
}
.workflow-employee-toggle.toggle-switch.active .toggle-slider {
  transform: translateX(20px);
}
</style>
