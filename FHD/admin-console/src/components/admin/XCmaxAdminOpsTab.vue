<template>
  <div class="xcmax-admin-ops">
    <div class="ops-toolbar">
      <button class="btn btn-secondary btn-sm" type="button" :disabled="loading" @click="refresh">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
        {{ loading ? '刷新中…' : '刷新编制/任务' }}
      </button>
    </div>

    <div v-if="errorMessage" class="ops-error">{{ errorMessage }}</div>

    <div class="admin-card">
      <div class="card-header">
        <h3>编制与健康</h3>
        <span class="status-badge" :class="dutyHealth.ok ? 'badge-ok' : 'badge-warn'">
          {{ dutyHealth.ok ? '正常' : '待处理' }}
        </span>
      </div>
      <dl class="card-info">
        <dt>计划编制</dt>
        <dd>{{ dutyHealth.plannedCount }}</dd>
        <dt>已注册</dt>
        <dd>{{ dutyHealth.registeredCount }}</dd>
        <dt>本地已装</dt>
        <dd>{{ dutyHealth.localInstalledCount }}</dd>
        <dt>编制缺口</dt>
        <dd>{{ dutyHealth.missingEmployees.length || 0 }}</dd>
      </dl>
      <ul v-if="dutyHealth.missingEmployees.length" class="ops-missing-list">
        <li v-for="id in dutyHealth.missingEmployees" :key="id">{{ id }}</li>
      </ul>
    </div>

    <div class="admin-card">
      <div class="card-header">
        <h3>调度下发</h3>
      </div>
      <label class="ops-label">任务描述</label>
      <textarea
        v-model="dispatchText"
        class="ops-textarea"
        rows="3"
        placeholder="例如：日更编排 / 员工大会前检查"
      />
      <div class="card-actions">
        <button
          class="btn btn-primary btn-sm"
          type="button"
          :disabled="dispatching || !dispatchText.trim()"
          @click="submitDispatch"
        >
          {{ dispatching ? '下发中…' : 'POST /api/xcmax/ops/dispatch' }}
        </button>
      </div>
      <pre v-if="dispatchResult" class="ops-json">{{ dispatchResult }}</pre>
    </div>

    <div class="admin-card admin-card--wide">
      <div class="card-header">
        <h3>编排任务</h3>
        <span class="status-badge badge-info">{{ jobs.length }} 条</span>
      </div>
      <table v-if="jobs.length" class="module-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>状态</th>
            <th>摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="job in jobs" :key="job.id">
            <td class="mono small">{{ job.id }}</td>
            <td>{{ job.status || '—' }}</td>
            <td class="small">{{ job.summary || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-hint">暂无任务，可先下发调度或点击刷新。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { appAlert } from '@/utils/appDialog'

const loading = ref(false)
const dispatching = ref(false)
const errorMessage = ref('')
const dispatchText = ref('日更编排检查')
const dispatchResult = ref('')

const dutyHealth = ref({
  ok: false,
  plannedCount: 0,
  registeredCount: 0,
  localInstalledCount: 0,
  missingEmployees: [] as string[],
})

type JobRow = { id: string; status?: string; summary?: string }
const jobs = ref<JobRow[]>([])

function pickMissing(raw: Record<string, unknown>): string[] {
  const staffing = raw.staffing as Record<string, unknown> | undefined
  const missing = staffing?.missing_employees
  if (!Array.isArray(missing)) return []
  return missing.map((x) => String(x)).filter(Boolean)
}

async function refresh() {
  loading.value = true
  errorMessage.value = ''
  try {
    const health = await xcmaxOpsApi.dutyHealth()
    const h = health && typeof health === 'object' ? (health as Record<string, unknown>) : {}
    dutyHealth.value = {
      ok: h.ok === true || h.success === true,
      plannedCount: Number(h.planned_local_installed_count ?? h.planned_count ?? 0),
      registeredCount: Number(
        Array.isArray(h.registered_employee_ids) ? h.registered_employee_ids.length : 0,
      ),
      localInstalledCount: Number(h.planned_local_installed_count ?? 0),
      missingEmployees: pickMissing(h),
    }
    const jobRes = await xcmaxOpsApi.listJobs(30)
    const rows =
      (jobRes as { data?: unknown })?.data ??
      (jobRes as { jobs?: unknown })?.jobs ??
      jobRes
    const list = Array.isArray(rows) ? rows : []
    jobs.value = list.map((row, i) => {
      const r = row && typeof row === 'object' ? (row as Record<string, unknown>) : {}
      return {
        id: String(r.id ?? r.job_id ?? i),
        status: String(r.status ?? r.state ?? ''),
        summary: String(r.task_description ?? r.summary ?? r.message ?? ''),
      }
    })
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function submitDispatch() {
  dispatching.value = true
  dispatchResult.value = ''
  try {
    const res = await xcmaxOpsApi.dispatch({ task_description: dispatchText.value.trim() })
    dispatchResult.value = JSON.stringify(res, null, 2)
    await refresh()
  } catch (e) {
    await appAlert(e instanceof Error ? e.message : String(e))
  } finally {
    dispatching.value = false
  }
}

onMounted(() => {
  void refresh()
})
</script>

<style scoped>
.xcmax-admin-ops {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ops-toolbar {
  display: flex;
  justify-content: flex-end;
}

.ops-error {
  color: #b91c1c;
  font-size: 13px;
}

.ops-label {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}

.ops-textarea {
  width: 100%;
  font-family: inherit;
  font-size: 13px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid rgba(15, 23, 42, 0.15);
  resize: vertical;
}

.ops-json {
  margin-top: 10px;
  padding: 10px;
  font-size: 11px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  overflow: auto;
  max-height: 200px;
}

.ops-missing-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: #64748b;
}

.admin-card {
  background: #fff;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 12px;
  padding: 16px 18px;
}

.admin-card--wide {
  grid-column: 1 / -1;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.card-header h3 {
  margin: 0;
  font-size: 15px;
}

.card-info {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 6px 12px;
  font-size: 13px;
}

.card-actions {
  margin-top: 10px;
}

.module-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.module-table th,
.module-table td {
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  padding: 8px 6px;
  text-align: left;
}

.mono {
  font-family: ui-monospace, monospace;
}

.small {
  font-size: 11px;
}

.empty-hint {
  color: #64748b;
  font-size: 13px;
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
}

.badge-ok {
  background: #dcfce7;
  color: #166534;
}

.badge-warn {
  background: #fef3c7;
  color: #92400e;
}

.badge-info {
  background: #e0f2fe;
  color: #0369a1;
}
</style>
