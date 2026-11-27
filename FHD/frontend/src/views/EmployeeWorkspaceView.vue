<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import PixelOfficeScene from '@/components/workflow/PixelOfficeScene.vue'
import { resolveDeskStatusLine, useWorkflowEmployeeDesks } from '@/composables/useWorkflowEmployeeDesks'
import { useDutyRoster } from '@/composables/useDutyRoster'
import { isCustomPhaseEmployeeCarrierModId } from '@/utils/modWorkflowEmployees'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { useWorkflowEmployeeRegistrySync } from '@/composables/useWorkflowEmployeeRegistrySync'
import { useWorkspaceDeskSelection } from '@/composables/useWorkspaceDeskSelection'
import { employeeStatusOfTask } from '@/utils/workflowEmployeeTaskState'
import { taskStatusLabel } from '@/utils/taskWorkspacePresentation'
import { ENTERPRISE_ORG_LAYERS, resolveEnterpriseOrgLayer } from '@/constants/enterpriseWorkflowEstablishment'
import type { DutyDepartment } from '@/domain/yuangonDutyRoster'
import type { OfficeZone } from '@/utils/pixelOffice'

const isAdminConsole = isAdminConsoleSpa()
const { allPlannedIds, departments, ensureLoaded, error: rosterError } = useDutyRoster()
const { error: registryError, refresh: refreshRegistry } = useWorkflowEmployeeRegistrySync()
const { desks, syncState } = useWorkflowEmployeeDesks()
const workspaceDesks = computed(() => desks.value.filter(row => isAdminConsole
  ? allPlannedIds.value.has(row.empId)
  : !isCustomPhaseEmployeeCarrierModId(row.carrierModId || row.hostModId)))
const route = useRoute()
const { selectedEmpId, routeFocusedEmployeeId, selectDesk } = useWorkspaceDeskSelection(workspaceDesks)
const active = ref(true)
const panelDesk = computed(() => active.value && route.name === 'workflow-employee-space'
  ? workspaceDesks.value.find(row => row.empId === routeFocusedEmployeeId.value)
  : undefined)
const adminColors = ['#cd9964', '#709c74', '#6c99ad', '#9c82b8', '#7b8dc3', '#b28376']
const zones = computed<OfficeZone[]>(() => {
  if (isAdminConsole) return Object.entries(departments.value).map(([id, value], index) => {
    const department = value as DutyDepartment
    return { id, label: department.label, color: adminColors[index % adminColors.length],
      employeeIds: [...new Set(Object.values(department.subzones || {}).flatMap(zone => zone.ids))],
      detail: Object.values(department.subzones || {}).map(zone => zone.label.replace(/\s+[OPBSR][\w/–-]*$/, '')).join(' · ') }
  })
  return ENTERPRISE_ORG_LAYERS.map(zone => ({ ...zone, employeeIds: workspaceDesks.value
    .filter(row => resolveEnterpriseOrgLayer(row.empId, row.shortName, row.panelTitle, row.enterpriseLayer) === zone.id).map(row => row.empId) }))
})
const panelDepartment = computed(() => zones.value.find(zone => zone.employeeIds.includes(panelDesk.value?.empId || ''))?.label)

function updateEmployeePanel(visible: boolean) {
  if (!visible && panelDesk.value) selectDesk(null)
}

onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false })
onMounted(() => { if (isAdminConsole) void ensureLoaded() })
</script>

<template>
  <div id="view-workflow-employee-space" class="page-view">
    <div class="page-content" data-page-ready="true">
      <PixelOfficeScene
        id="ews-workflow-monitor"
        data-tour="employee-workspace-desks"
        :desks="workspaceDesks"
        :zones="zones"
        :selected-emp-id="selectedEmpId"
        @select="selectDesk"
      >
        <p v-if="syncState.error" class="employee-office-notice" role="alert">{{ syncState.error }}；恢复连接后将重新核对工位状态。</p>
        <p v-if="registryError" class="employee-office-notice" role="alert">员工目录同步失败：{{ registryError }} <button type="button" @click="refreshRegistry">重新同步目录</button></p>
        <p v-if="rosterError && isAdminConsole" class="employee-office-notice" role="alert">部门编制加载失败：{{ rosterError.message }}</p>
      </PixelOfficeScene>
    </div>
    <el-dialog
      :model-value="Boolean(panelDesk)"
      :title="panelDesk?.shortName || '员工详情'"
      width="min(460px, calc(100vw - 32px))"
      align-center
      append-to-body
      destroy-on-close
      @update:model-value="updateEmployeePanel"
    >
      <div v-if="panelDesk" class="employee-panel">
        <div class="employee-panel-status">
          <span v-if="panelDepartment">{{ panelDepartment }}</span>
          <strong>{{ resolveDeskStatusLine(panelDesk) }}</strong>
        </div>
        <h3>近期任务</h3>
        <ul v-if="panelDesk.tasks?.length" class="employee-panel-tasks">
          <li v-for="task in panelDesk.tasks.slice(0, 3)" :key="task.task_id">
            <router-link :to="{ name: 'employee-workbench', query: { employee: panelDesk.empId, task: task.task_id } }">
              <span>{{ task.title }}</span>
              <small>{{ syncState.stale ? '状态待核实' : taskStatusLabel(employeeStatusOfTask(task, panelDesk.empId)) }}</small>
            </router-link>
          </li>
        </ul>
        <p v-else>{{ syncState.stale ? '任务记录待同步' : '暂无可见任务' }}</p>
        <router-link class="employee-panel-workbench" :to="{ name: 'employee-workbench', query: { employee: panelDesk.empId } }">
          查看全部任务
        </router-link>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped src="./EmployeeWorkspaceView.css"></style>
