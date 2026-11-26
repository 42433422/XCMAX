<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted } from 'vue'
import { useWorkflowEmployeeDesks } from '@/composables/useWorkflowEmployeeDesks'
import WorkflowEmployeeInspector from '@/components/workflow/WorkflowEmployeeInspector.vue'
import { useDutyRoster } from '@/composables/useDutyRoster'
import { isCustomPhaseEmployeeCarrierModId } from '@/utils/modWorkflowEmployees'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { useWorkflowEmployeeRegistrySync } from '@/composables/useWorkflowEmployeeRegistrySync'
import { useWorkspaceDeskSelection } from '@/composables/useWorkspaceDeskSelection'
import { employeeStatusOfTask } from '@/utils/workflowEmployeeTaskState'
import { ENTERPRISE_ORG_LAYERS, resolveEnterpriseOrgLayer } from '@/constants/enterpriseWorkflowEstablishment'
import type { DutyDepartment } from '@/domain/yuangonDutyRoster'
import type { OfficeZone } from '@/utils/pixelOffice'

const PixelOfficeScene = defineAsyncComponent(() => import('./PixelOfficeScene.vue'))
const isAdminConsole = isAdminConsoleSpa()
const { allPlannedIds, departments, ensureLoaded, error: rosterError } = useDutyRoster()
const { error: registryError, refresh: refreshRegistry } = useWorkflowEmployeeRegistrySync()
const { desks, isBusy, syncState } = useWorkflowEmployeeDesks()
const workspaceDesks = computed(() => desks.value.filter(row => isAdminConsole
  ? allPlannedIds.value.has(row.empId)
  : !isCustomPhaseEmployeeCarrierModId(row.carrierModId || row.hostModId)))
const { selectedEmpId, selectDesk } = useWorkspaceDeskSelection(workspaceDesks)
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
const working = computed(() => workspaceDesks.value.filter(isBusy).length)
const waitingStates = new Set(['queued', 'pending', 'accepted', 'waiting_user', 'waiting_approval', 'awaiting_approval', 'paused'])
const attentionStates = new Set(['failed', 'blocked', 'unknown', 'rejected', 'timed_out'])
const waiting = computed(() => workspaceDesks.value.filter(row => row.snapshot?.officeState === 'waiting' || row.tasks?.some(task => waitingStates.has(employeeStatusOfTask(task, row.empId)))).length)
const attention = computed(() => workspaceDesks.value.filter(row => row.snapshot?.officeState === 'error' || row.tasks?.some(task => attentionStates.has(employeeStatusOfTask(task, row.empId)))).length)
const completed = computed(() => new Set(workspaceDesks.value.flatMap(row => (row.tasks || [])
  .filter(task => task.status === 'completed' && employeeStatusOfTask(task, row.empId) === 'completed')
  .map(task => task.task_id))).size)
const statusText = computed(() => syncState.value.stale ? '状态待核实' : syncState.value.connected ? '实时同步' : '正在连接实时更新')
const graphLocation = computed(() => ({ name: isAdminConsole ? 'duty-roster-graph' : 'workflow-employee-stitch-full', query: { employee: selectedEmpId.value || undefined } }))
const workbenchLocation = computed(() => ({ name: 'employee-workbench', query: { employee: selectedEmpId.value || undefined } }))
function onInspectorSelect(empId: string | null) { selectDesk(empId) }
onMounted(() => { if (isAdminConsole) void ensureLoaded() })
</script>

<template>
  <section class="ews" aria-labelledby="ews-heading" data-tour="employee-workspace-desks" data-page-ready="true">
    <header class="ews-header">
      <div>
        <p class="ews-kicker">{{ isAdminConsole ? '管理中心 · 六部门' : '企业办公室 · 四部门' }}</p>
        <h2 id="ews-heading">员工空间</h2>
        <p class="ews-description">按部门查看员工当前任务，点击工位查看进度与交付结果。</p>
      </div>
      <div class="ews-header-actions">
        <span class="ews-sync" :class="{ 'ews-sync--stale': syncState.stale }" role="status"><i aria-hidden="true" />{{ statusText }}</span>
        <router-link :to="workbenchLocation" class="ews-link">员工工作台 ↗</router-link>
        <router-link :to="graphLocation" class="ews-link">员工图谱 ↗</router-link>
      </div>
    </header>
    <div class="ews-stats" aria-label="员工任务概况">
      <div><span>{{ isAdminConsole ? '平台员工' : '企业员工' }}</span><strong>{{ workspaceDesks.length }}</strong></div>
      <div><span>正在工作</span><strong class="ews-stat--working">{{ syncState.stale ? '—' : working }}</strong></div>
      <div><span>等待处理</span><strong class="ews-stat--waiting">{{ syncState.stale ? '—' : waiting }}</strong></div>
      <div><span>需要关注</span><strong class="ews-stat--attention">{{ syncState.stale ? '—' : attention }}</strong></div>
      <div><span>近期完成任务</span><strong>{{ syncState.stale ? '—' : completed }}</strong></div>
    </div>
    <p class="ews-coverage">任务统计基于最近最多 200 条可见记录，并非全历史总量。等待与需关注人数可重叠。</p>
    <p v-if="syncState.error" class="ews-notice" role="alert">{{ syncState.error }}；恢复连接后将重新核对任务状态。</p>
    <p v-if="registryError" class="ews-notice" role="alert">员工目录同步失败：{{ registryError }} <button type="button" @click="refreshRegistry">重新同步目录</button></p>
    <p v-if="rosterError && isAdminConsole" class="ews-notice" role="alert">部门编制加载失败：{{ rosterError.message }}</p>
    <div id="ews-workflow-monitor" class="ews-layout">
      <div class="ews-office">
        <PixelOfficeScene :desks="workspaceDesks" :zones="zones" :selected-emp-id="selectedEmpId" @select="selectDesk" />
        <div v-if="!workspaceDesks.length" class="ews-empty">
          <strong>{{ isAdminConsole ? '等待平台员工目录同步' : '当前企业暂无已安装员工' }}</strong>
          <p>部门分区已保留，员工注册后会出现在对应工位。</p>
        </div>
      </div>
      <WorkflowEmployeeInspector :selected-emp-id="selectedEmpId" :desks="workspaceDesks" hide-workspace-link @update:selected-emp-id="onInspectorSelect" />
    </div>
  </section>
</template>

<style scoped src="./EmployeeWorkspaceScene.css"></style>
