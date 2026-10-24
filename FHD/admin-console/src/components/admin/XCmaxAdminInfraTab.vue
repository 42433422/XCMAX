<template>
  <div class="xcmax-admin-infra">
    <div class="ops-toolbar"><span>核对岗位、员工包、服务连接与调度；实际交付另读原单回执。</span><button class="btn btn-secondary btn-sm" type="button" :disabled="loading" @click="refresh">{{ loading ? '刷新中…' : '刷新基础设施' }}</button></div>
    <p v-if="errorMessage" class="ops-error" role="alert">{{ errorMessage }}</p>
    <section class="admin-card">
      <div class="card-header"><h3>岗位与服务状态</h3><span class="status-badge" :class="checkState.ready ? 'badge-ok' : 'badge-warn'">{{ checkState.label }}</span></div>
      <dl class="card-info">
        <dt>计划岗位</dt><dd>{{ plannedCount ?? '待核实' }}</dd>
        <dt>目录缺岗</dt><dd>{{ closureKnown ? remoteMissing.length : '待核实' }}</dd>
        <dt>本端缺包</dt><dd>{{ closureKnown ? localMissing.length : '待核实' }}</dd>
        <dt>本端已安装</dt><dd>{{ localInstalled ?? '待核实' }}</dd>
        <dt>远端连接</dt><dd>{{ remoteReachable === null ? '待核实' : remoteReachable ? '可达' : '不可达' }}</dd>
        <dt>员工调度</dt><dd>{{ schedulerRunning === null ? '待核实' : schedulerRunning ? '运行中' : '未运行' }}</dd>
      </dl>
      <p class="muted">本端指提供当前运行数据的设备；包已安装、服务可达和业务完成分别核对。</p>
      <details v-if="closureDetail"><summary>查看闭环依据</summary><pre class="ops-json">{{ closureDetail }}</pre></details>
    </section>
    <section class="admin-card" aria-label="未闭环原因与下一步">
      <h3>未闭环原因与下一步</h3>
      <p v-if="!closureKnown" class="muted">闭环依据尚未读全，请先重新读取；不能据此认定没有待办。</p>
      <ul v-else-if="blockers.length" class="blocker-list">
        <li v-for="(blocker, index) in blockers" :key="String(blocker.code || index)">
          <strong>{{ blockerInfo(blocker).label }} · {{ count(blocker.count) }} 项</strong>
          <p>责任方：{{ typeof blocker.owner === 'string' && blocker.owner.trim() ? blocker.owner : '尚未记录，待指派' }}</p>
          <p>下一步：{{ blockerInfo(blocker).action }}</p>
          <small v-if="Array.isArray(blocker.employee_ids)">员工编号：{{ blocker.employee_ids.join('、') }}</small>
        </li>
      </ul>
      <p v-else class="muted">{{ closure?.deliverable === true ? '本次未报告岗位或员工包缺口；继续核对服务、调度与实际任务回执。' : '闭环状态尚未通过，但未提供明确原因；请核对依据并记录责任方。' }}</p>
      <p v-if="remoteReachable === false">远端连接未通过；责任方尚未记录。请核对远端服务及网络后重新读取。</p>
      <p v-if="schedulerRunning === false">员工调度未运行；责任方尚未记录。请到员工自治核对失败与未运行任务，处理后回读。</p>
      <nav class="ops-links"><router-link :to="{ name: 'duty-roster-graph', query: { view: 'department' } }">查看编制与包状态</router-link><router-link :to="{ name: 'employee-autonomy' }">查看员工运行</router-link><router-link :to="{ name: 'autonomy-approval-hub' }">查看待审请求</router-link></nav>
    </section>
    <section class="admin-card">
      <h3>计划编制部门（非运行人数）</h3>
      <ul class="dept-list"><li v-for="(dept, id) in YUANGON_AREAS" :key="id"><strong>{{ dept.label }}</strong><span>{{ dept.ids.length }} 个计划岗位 · 本端已装 {{ departmentCount(dept.ids, 'installed') }} · 目录缺岗 {{ departmentCount(dept.ids, 'missing') }} · 本端缺包 {{ departmentCount(dept.ids, 'local') }}</span></li></ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { api } from '@/api'
import { YUANGON_AREAS } from '@/domain/yuangonDutyRoster'
import { buildDutyRosterRows } from '@/utils/dutyRosterEmployeeList'

type RecordValue = Record<string, unknown>
const loading = ref(false), errorMessage = ref('')
const closure = ref<RecordValue | null>(null)
const remoteReachable = ref<boolean | null>(null), schedulerRunning = ref<boolean | null>(null)
const rosterRows = ref<ReturnType<typeof buildDutyRosterRows>>([])
const count = (value: unknown) => typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : '待核实'
const ids = (value: unknown) => Array.isArray(value) ? [...new Set(value.filter((id): id is string => typeof id === 'string' && !!id.trim()))] : []
const idListKnown = (value: unknown) => Array.isArray(value) && value.every(id => typeof id === 'string' && !!id.trim())
const closureKnown = computed(() => !!closure.value && typeof closure.value.deliverable === 'boolean' && Array.isArray(closure.value.blockers) && closure.value.blockers.every(row => row && typeof row === 'object' && !Array.isArray(row)) && ['missing_local_employee_packs', 'planned_employee_ids', 'missing_remote_employees', 'local_employee_pack_ids'].every(key => idListKnown(closure.value?.[key])))
const plannedCount = computed(() => closureKnown.value ? ids(closure.value?.planned_employee_ids).length : null)
const localInstalled = computed(() => closureKnown.value && typeof closure.value?.planned_local_installed_count === 'number' ? count(closure.value.planned_local_installed_count) : null)
const localMissing = computed(() => closureKnown.value ? ids(closure.value?.planned_employee_ids).filter(id => !ids(closure.value?.local_employee_pack_ids).includes(id)) : [])
const remoteMissing = computed(() => ids(closure.value?.missing_remote_employees))
const blockers = computed<RecordValue[]>(() => {
  const rows: RecordValue[] = Array.isArray(closure.value?.blockers) ? closure.value.blockers.filter((row): row is RecordValue => !!row && typeof row === 'object' && !Array.isArray(row)) : []
  for (const [code, employeeIds] of [['REMOTE_STAFFING_GAP', remoteMissing.value], ['LOCAL_EMPLOYEE_PACK_MISSING', localMissing.value]] as const) {
    if (employeeIds.length && !rows.some(row => row.code === code)) rows.push({ code, count: employeeIds.length, employee_ids: employeeIds })
  }
  return rows
})
const closureDetail = computed(() => closure.value ? JSON.stringify({ deliverable: closure.value.deliverable, blockers: closure.value.blockers, next_actions: closure.value.next_actions }, null, 2) : '')
const checkState = computed(() => {
  let label = '本次检查满足', ready = false
  if (loading.value) label = '读取中'
  else if (!closureKnown.value || errorMessage.value) label = '部分状态待核实'
  else if (!plannedCount.value) label = '计划岗位待核对'
  else if (blockers.value.length || localMissing.value.length || remoteMissing.value.length || closure.value?.deliverable !== true) label = '尚有未闭环项'
  else if (typeof localInstalled.value !== 'number' || localInstalled.value !== plannedCount.value) label = '安装计数待核对'
  else if (remoteReachable.value === null || schedulerRunning.value === null) label = '服务或调度待核实'
  else if (!remoteReachable.value) label = '远端不可达'
  else if (!schedulerRunning.value) label = '调度未运行'
  else ready = true
  return { label, ready }
})
const departmentCount = (departmentIds: string[], status: string) => !closureKnown.value ? '待核实' : status === 'local' ? departmentIds.filter(id => localMissing.value.includes(id)).length : departmentIds.filter(id => rosterRows.value.some(row => row.pkgId === id && row.status === status)).length
function blockerInfo(blocker: RecordValue) {
  return ({
    REMOTE_STAFFING_GAP: { label: '服务目录缺少编制岗位', action: '打开编制图谱核对员工编号，再补齐对应目录登记。' },
    LOCAL_EMPLOYEE_PACK_MISSING: { label: '当前运行端缺少员工包', action: '选择具体员工查看包状态，核对市场权益与平台后安装需要的包，再重新读取。' },
    PENDING_CHANGE_REQUESTS: { label: '仍有变更请求待处理', action: '打开审批中心按原请求处理，再核对执行回执。' },
  } as Record<string, { label: string; action: string }>)[String(blocker.code)] || { label: String(blocker.code || '其它未闭环项'), action: '核对该项原始依据并记录责任方与处理结果。' }
}
function object(value: unknown): RecordValue {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('返回状态无法识别')
  const raw = value as RecordValue
  const result = raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data) ? raw.data as RecordValue : raw
  if (raw.success === false) throw new Error('接口未成功返回状态')
  return result
}
async function refresh() {
  loading.value = true
  errorMessage.value = ''
  closure.value = null; remoteReachable.value = schedulerRunning.value = null; rosterRows.value = []
  const errors: string[] = []
  const results = await Promise.allSettled([xcmaxOpsApi.closureStatus(), api.get('/api/xcmax/admin/remote-status'), xcmaxOpsApi.dutyHealth()])
  const labels = ['闭环依据', '远端连接', '调度状态']
  results.forEach((result, index) => {
    try {
      if (result.status === 'rejected') throw result.reason
      const data = object(result.value)
      if (index === 0) { closure.value = data; rosterRows.value = buildDutyRosterRows(data) }
      if (index === 1) remoteReachable.value = typeof data.reachable === 'boolean' ? data.reachable : null
      if (index === 2) {
        const remote = data.remote_health && typeof data.remote_health === 'object' ? data.remote_health as RecordValue : {}
        const scheduler = object(data.employee_scheduler || remote.employee_scheduler || data.scheduler || {})
        schedulerRunning.value = typeof scheduler.running === 'boolean' ? scheduler.running : null
      }
    } catch (cause) { errors.push(`${labels[index]}读取失败：${cause instanceof Error ? cause.message : '暂时无法核实'}`) }
  })
  errorMessage.value = errors.join('；')
  loading.value = false
}
onMounted(() => { void refresh() })
</script>

<style scoped>
.xcmax-admin-infra { display: flex; flex-direction: column; gap: 16px; }
.ops-toolbar, .card-header, .ops-links { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
.admin-card { padding: 16px 18px; }
h3 { margin: 0 0 12px; font-size: 15px; }
.card-info { display: grid; grid-template-columns: minmax(90px, auto) 1fr; gap: 8px 16px; font-size: 13px; }
dd { margin: 0; overflow-wrap: anywhere; }
.ops-error { color: var(--admin-danger-text, #b91c1c); }
.ops-json { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; }
.dept-list, .blocker-list { padding: 0; list-style: none; display: grid; gap: 12px; }
.dept-list li { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 12px; }
.blocker-list li { padding: 12px; border: 1px solid var(--admin-border, #d0d7e2); border-radius: var(--admin-control-radius, 8px); overflow-wrap: anywhere; }
.blocker-list p { margin: 6px 0; }
.status-badge { padding: 4px 10px; border-radius: 999px; font-size: 12px; }
.badge-ok { background: var(--admin-success-bg, #dcfce7); color: var(--admin-success-text, #166534); }
.badge-warn { background: var(--admin-warning-bg, #fef3c7); color: var(--admin-warning-text, #92400e); }
</style>
