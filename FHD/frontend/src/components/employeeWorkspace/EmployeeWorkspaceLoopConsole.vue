<script setup lang="ts">
import 'element-plus/dist/index.css'
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import {
  ElAlert,
  ElButton,
  ElDialog,
  ElEmpty,
  ElInput,
  ElOption,
  ElSelect,
  ElTabPane,
  ElTabs,
  ElTag,
  ElTimeline,
  ElTimelineItem,
} from 'element-plus'
import agentRunsApi from '@/api/agentRuns'
import { useAgentTaskCenterStore } from '@/stores/agentTaskCenter'
import { employeeDirectoryScope, fetchEmployeeDirectory, type DirectoryEmployee } from '@/api/employeeDirectory'
import { taskStatusLabel, taskStatusOf } from '@/utils/taskWorkspacePresentation'
import { taskSummariesToTaskItems } from '@/utils/agentTaskWorkspaceModel'
import AgentTaskRuntimePanel from '@/components/chat/AgentTaskRuntimePanel.vue'
import TaskExecutionGraph from './TaskExecutionGraph.vue'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { employeeIdOfTask, taskEmployeeIds } from '@/utils/workflowEmployeeTaskState'

const props = withDefaults(defineProps<{ initialPane?: string; archiveOnly?: boolean }>(), { initialPane: 'flow', archiveOnly: false })
const store = useAgentTaskCenterStore()
const { tasks, selectedTask, selectedTaskId, loading, error, runtime, actionPending, connected, stale } = storeToRefs(store)
const route = useRoute()
const router = useRouter()
const pane = ref(props.initialPane)
const search = ref('')
const filter = ref('all')
const compose = ref(false)
const employees = ref<DirectoryEmployee[]>([])
const employeeId = ref('')
const employeeError = ref('')
const taskText = ref('')
const submitting = ref(false)
const submitError = ref('')
const pendingSubmission = ref<{ taskId: string; fingerprint: string } | null>(null)
let scopeVersion = 0
let directoryRequest = 0
const canSubmit = computed(
  () => !submitting.value && !employeeError.value && !!taskText.value.trim() && employees.value.some((e) => e.pack_id === employeeId.value && e.runtime_ok),
)
const employeeFilter = computed(() => typeof route.query.employee === 'string' ? route.query.employee.trim() : '')
const employeeFilterLabel = computed(() => employees.value.find(e => e.pack_id === employeeFilter.value)?.label || employeeFilter.value)
const selected = computed(() => (selectedTask.value?.task_id === selectedTaskId.value ? selectedTask.value : null))
const selectedStatus = computed(() => taskStatusOf(selected.value))
const selectedUncertain = computed(() => selectedStatus.value === 'unknown')
const activeRun = computed(
  () => selected.value?.active_run || selected.value?.runs?.find((r) => r.run_id === selected.value?.active_run_id),
)
const assignedEmployee = computed(() => {
  const id = selected.value ? employeeIdOfTask(selected.value) : ''
  return employees.value.find((employee) => employee.pack_id === id)?.label || id
})
const taskItem = computed(() => (selected.value ? taskSummariesToTaskItems([selected.value])[0] : null))
const visibleTasks = computed(() =>
  tasks.value.filter((task) => {
    if (employeeFilter.value && !taskEmployeeIds(task).includes(employeeFilter.value)) return false
    const matches = `${task.title} ${task.task_id}`.toLowerCase().includes(search.value.trim().toLowerCase())
    const status = taskStatusOf(task)
    const active = ['queued', 'planning', 'running', 'retrying'].includes(status)
    const attention = ['blocked', 'failed', 'waiting_user', 'paused', 'unknown'].includes(status)
    return (
      matches &&
      (filter.value === 'all' ||
        (filter.value === 'active' && active) ||
        (filter.value === 'attention' && attention) ||
        (filter.value === 'completed' && status === 'completed'))
    )
  }),
)
const executor = computed(() => runtime.value.executor)
const location = computed(() => selected.value?.workspace_path || '')
const actions = [
  { key: 'approve', label: '审批并执行' },
  { key: 'pause', label: '暂停' },
  { key: 'resume', label: '恢复' },
  { key: 'cancel', label: '取消' },
  { key: 'retry', label: '重试' },
] as const
function statusType(status: string): 'success' | 'danger' | 'warning' | 'info' | 'primary' {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (['blocked', 'waiting_user', 'paused', 'unknown'].includes(status)) return 'warning'
  if (['running', 'planning', 'retrying'].includes(status)) return 'primary'
  return 'info'
}
function time(value?: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}
async function selectTask(id: string) {
  const version = scopeVersion
  selectedTaskId.value = id
  selectedTask.value = null
  await router.replace({ query: { ...route.query, task: id } })
  if (version !== scopeVersion) return
  await store.refreshDetail()
}
function openEmployeeSurface(name: string) {
  const employee = (selected.value ? employeeIdOfTask(selected.value) : '') || employeeFilter.value
  void router.push({ name, query: { employee: employee || undefined } })
}
async function refresh() {
  await store.refresh()
  if (selectedTaskId.value) await store.refreshDetail()
}
async function loadEmployees() {
  const version = scopeVersion
  const request = ++directoryRequest
  employeeError.value = ''
  employees.value = []
  try {
    const rows = await fetchEmployeeDirectory({ force: true })
    if (version !== scopeVersion || request !== directoryRequest) return
    employees.value = rows
    const requested = String(route.query.employee || '')
    if (!pendingSubmission.value && employees.value.some((e) => e.pack_id === requested && e.runtime_ok)) employeeId.value = requested
  } catch {
    if (version !== scopeVersion || request !== directoryRequest) return
    employees.value = []
    employeeError.value = '员工目录读取失败'
  }
}
function openCompose() {
  compose.value = true
  void loadEmployees()
  if (route.query.compose) void router.replace({ query: { ...route.query, compose: undefined } })
}
async function submit() {
  if (!canSubmit.value) return
  const version = scopeVersion
  const params = { employee_id: employeeId.value, task: taskText.value.trim() }
  const fingerprint = JSON.stringify(params)
  if (pendingSubmission.value && pendingSubmission.value.fingerprint !== fingerprint) {
    submitError.value = '上次提交结果尚未确认，请先刷新任务列表；请勿更换内容后重复提交。'
    return
  }
  pendingSubmission.value ||= { taskId: `employee-${crypto.randomUUID()}`, fingerprint }
  submitting.value = true
  submitError.value = ''
  try {
    const response = await agentRunsApi.createTask({
      task_id: pendingSubmission.value.taskId,
      title: params.task.slice(0, 80),
      message: params.task,
      tool_id: 'employee',
      action: 'execute',
      params,
      runtime_context: {
        source: isAdminConsoleSpa() ? 'admin_employee_workspace' : 'desktop_employee_workbench',
        client_surface: isAdminConsoleSpa() ? 'admin_console' : 'enterprise_desktop',
      },
    })
    if (version !== scopeVersion) return
    if (response.success === false || !response.data?.run_id) throw new Error(response.message || '任务提交未确认')
    const id = pendingSubmission.value.taskId
    pendingSubmission.value = null
    compose.value = false
    taskText.value = ''
    await store.refresh()
    if (version !== scopeVersion) return
    await selectTask(id)
  } catch (reason) {
    if (version !== scopeVersion) return
    const status = Number((reason as { status?: number })?.status || 0)
    if ([400, 401, 403, 404, 422].includes(status)) pendingSubmission.value = null
    submitError.value = `${reason instanceof Error ? reason.message : '提交未确认'}${pendingSubmission.value ? '。再次提交将核对同一任务。' : ''}`
  } finally {
    if (version === scopeVersion) submitting.value = false
  }
}
function backToList() {
  selectedTaskId.value = ''
  selectedTask.value = null
  void router.replace({ query: { ...route.query, task: undefined } })
}
function openConversation() {
  if (!selected.value) return
  void router.push({
    name: 'task-workspace',
    params: { taskId: selected.value.task_id },
    query: { conversation: selected.value.conversation_id || selected.value.task_id },
  })
}
watch(
  () => tasks.value.find((t) => t.task_id === selectedTaskId.value)?.updated_at,
  () => {
    if (selectedTaskId.value) void store.refreshDetail()
  },
)
watch(
  () => route.query.task,
  (id) => {
    if (typeof id === 'string' && id !== selectedTaskId.value) {
      selectedTaskId.value = id
      selectedTask.value = null
      void store.refreshDetail()
    }
  },
)
watch(() => route.query.compose, (value) => { if (value === '1') openCompose() })
watch(employeeDirectoryScope, () => {
  scopeVersion += 1
  pendingSubmission.value = null
  compose.value = false
  employeeId.value = ''
  taskText.value = ''
  submitting.value = false
  submitError.value = ''
  void loadEmployees()
}, { flush: 'sync' })
watch(employeeFilter, () => {
  if (route.query.task || route.query.compose === '1') return
  const next = visibleTasks.value[0]?.task_id
  if (next) void selectTask(next)
  else { selectedTaskId.value = ''; selectedTask.value = null }
})
onMounted(async () => {
  store.start()
  void loadEmployees()
  await refresh()
  const previous = visibleTasks.value.some(task => task.task_id === selectedTaskId.value) ? selectedTaskId.value : ''
  const id = String(route.query.task || previous || visibleTasks.value[0]?.task_id || '')
  if (id) await selectTask(id)
  else { selectedTaskId.value = ''; selectedTask.value = null }
  if (route.query.compose === '1') openCompose()
})
onActivated(() => void refresh())
</script>

<template>
  <section class="employee-workspace" aria-label="员工任务工作台" data-page-ready="true">
    <header class="workspace-toolbar">
      <div>
        <h2>员工工作台</h2>
        <span class="workspace-runtime"
          ><i :class="{ online: runtime.running }" />{{ runtime.running ? '执行服务已启动' : '执行服务未启动'
          }}<template v-if="executor"> · {{ executor.host }}</template> · {{ stale ? '状态待核对' : connected ? '实时同步' : '定时核对' }}</span
        >
      </div>
      <div class="workspace-toolbar-actions">
        <el-button @click="openEmployeeSurface('workflow-employee-space')">员工空间</el-button>
        <el-button @click="openEmployeeSurface(isAdminConsoleSpa() ? 'duty-roster-graph' : 'workflow-employee-stitch-full')">员工图谱</el-button>
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button v-if="!archiveOnly" type="primary" @click="openCompose">新建任务</el-button>
      </div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-else-if="stale" title="正在核对最新任务状态；连接恢复后自动同步。" type="warning" :closable="false" show-icon />
    <div class="workspace-layout" :class="{ 'has-selection': selectedTaskId }">
      <aside class="workspace-list" aria-label="任务列表">
        <div class="workspace-list-tools">
          <el-button v-if="employeeFilter" text @click="router.replace({ query: { ...route.query, employee: undefined, task: undefined } })">{{ employeeFilterLabel }} · 查看全部员工</el-button>
          <el-input v-model="search" placeholder="搜索任务" clearable aria-label="搜索任务" />
          <el-select v-model="filter" aria-label="任务状态筛选">
            <el-option label="全部任务" value="all" /><el-option label="进行中" value="active" />
            <el-option label="需处理" value="attention" /><el-option label="执行完成" value="completed" />
          </el-select>
        </div>
        <div class="workspace-task-scroll">
          <button
            v-for="task in visibleTasks"
            :key="task.task_id"
            class="workspace-task"
            :class="{ selected: task.task_id === selectedTaskId }"
            :aria-current="task.task_id === selectedTaskId ? 'true' : undefined"
            @click="selectTask(task.task_id)"
          >
            <strong>{{ task.title }}</strong>
            <span
              ><el-tag :type="statusType(taskStatusOf(task))" size="small" effect="light">{{
                taskStatusOf(task) === 'completed' ? '执行完成' : taskStatusLabel(taskStatusOf(task))
              }}</el-tag
              ><small>{{ time(task.updated_at) }}</small></span
            >
          </button>
          <el-empty
            v-if="!visibleTasks.length"
            :description="loading ? '正在读取任务' : search || filter !== 'all' ? '没有匹配任务' : '暂无任务'"
            :image-size="64"
          />
        </div>
        <footer>{{ visibleTasks.length }} 个可见任务 · {{ runtime.active_count }} 个执行中</footer>
      </aside>
      <main class="workspace-detail">
        <template v-if="selected">
          <header class="workspace-task-header">
            <el-button
              class="workspace-mobile-back"
              text
              @click="backToList"
              >返回任务列表</el-button
            >
            <div class="workspace-task-heading">
              <h3>{{ selected.title }}</h3>
              <el-tag :type="statusType(selectedStatus)">{{
                selectedStatus === 'completed' ? '执行完成' : taskStatusLabel(selectedStatus)
              }}</el-tag>
            </div>
            <div class="workspace-facts">
              <span v-if="assignedEmployee">执行员工 <strong>{{ assignedEmployee }}</strong></span>
              <span
                >工作目录 <strong>{{ location || '未记录' }}</strong></span
              ><span
                >执行节点 <strong>{{ selected.execution?.lease_owner || '未记录' }}</strong></span
              >
            </div>
            <div class="workspace-controls">
              <template v-for="action in actions" :key="action.key"
                ><el-button
                  v-if="selected.capabilities?.[action.key] && (!archiveOnly || action.key === 'cancel')"
                  :loading="actionPending === action.key"
                  :disabled="!!actionPending || !!error || stale || selectedUncertain"
                  size="small"
                  @click="store.controlTask(selected.task_id, action.key)"
                  >{{ action.label }}</el-button
                ></template
              >
              <el-button size="small" @click="openConversation">任务对话</el-button>
            </div>
          </header>
          <el-tabs v-model="pane" class="workspace-tabs">
            <el-tab-pane label="执行流程" name="flow">
              <TaskExecutionGraph v-if="activeRun?.steps?.length" :steps="activeRun.steps" :run-id="activeRun.run_id" />
              <el-empty v-else description="尚未生成执行步骤" :image-size="80" />
            </el-tab-pane>
            <el-tab-pane :label="`执行记录 ${activeRun?.events?.length || 0}`" name="events">
              <div class="workspace-pane-scroll">
                <el-timeline v-if="activeRun?.events?.length"
                  ><el-timeline-item
                    v-for="event in [...activeRun.events].reverse()"
                    :key="event.event_id"
                    :timestamp="time(event.created_at)"
                    ><strong>{{ event.message || event.event_type }}</strong></el-timeline-item
                  ></el-timeline
                ><el-empty v-else description="暂无执行记录" :image-size="80" />
              </div>
            </el-tab-pane>
            <el-tab-pane :label="`结果与产物 ${activeRun?.artifacts?.length || 0}`" name="results">
              <div class="workspace-pane-scroll">
                <AgentTaskRuntimePanel
                  v-if="taskItem"
                  :task="taskItem"
                  :control-state="{ needsVerification: Boolean(archiveOnly || error || actionPending || stale || selectedUncertain) }"
                  @open="openConversation"
                  @refresh="refresh"
                  @approve="store.controlTask(selected.task_id, 'approve')"
                  @pause="store.controlTask(selected.task_id, 'pause')"
                  @resume="store.controlTask(selected.task_id, 'resume')"
                  @cancel="store.controlTask(selected.task_id, 'cancel')"
                  @retry="store.controlTask(selected.task_id, 'retry')"
                />
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
        <el-empty v-else :description="selectedTaskId ? '正在读取任务详情' : '选择任务，查看工作空间与执行流程'" :image-size="100"
          ><el-button v-if="!selectedTaskId" type="primary" @click="openCompose">新建任务</el-button></el-empty
        >
      </main>
    </div>
    <el-dialog
      v-model="compose"
      title="新建员工任务"
      width="520px"
      :close-on-click-modal="!submitting"
      :close-on-press-escape="!submitting"
      :show-close="!submitting"
      append-to-body
    >
      <form class="workspace-compose" @submit.prevent="submit">
        <el-alert v-if="employeeError" :title="employeeError" type="error" :closable="false" />
        <label
          >执行员工<el-select
            v-model="employeeId"
            filterable
            placeholder="选择员工"
            aria-label="执行员工"
            :disabled="submitting || !!pendingSubmission"
            ><el-option
              v-for="employee in employees"
              :key="employee.pack_id"
              :value="employee.pack_id"
              :label="employee.label"
              :disabled="!employee.runtime_ok"
              ><span>{{ employee.label }}</span
              ><small class="employee-option-area">{{ employee.runtime_ok ? employee.department : (employee.prompt_only ? '仅对话' : '不可执行') }}</small></el-option
            ></el-select
          ></label
        >
        <label
          >任务<el-input
            v-model="taskText"
            type="textarea"
            :rows="5"
            maxlength="2000"
            show-word-limit
            placeholder="填写任务和验收要求"
            aria-label="任务要求"
            :disabled="submitting || !!pendingSubmission"
        /></label>
        <div class="workspace-target" v-if="executor">
          <span>执行位置</span><strong>{{ executor.host }}</strong
          ><code>{{ executor.workspace_root }}</code>
        </div>
        <el-alert v-if="submitError" :title="submitError" type="error" :closable="false" />
        <div class="workspace-compose-actions">
          <el-button :disabled="submitting" @click="compose = false">关闭</el-button
          ><el-button type="primary" native-type="submit" :loading="submitting" :disabled="!canSubmit">{{
            pendingSubmission ? '核对并重试提交' : '派发任务'
          }}</el-button>
        </div>
      </form>
    </el-dialog>
  </section>
</template>
<style scoped src="./EmployeeWorkspaceLoopConsole.css"></style>
