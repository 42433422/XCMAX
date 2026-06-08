<template>
  <div class="xcmax-admin-infra">
    <div class="ops-toolbar">
      <button class="btn btn-secondary btn-sm" type="button" :disabled="loading" @click="refresh">
        <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
        {{ loading ? '刷新中…' : '刷新基础设施' }}
      </button>
    </div>

    <p v-if="errorMessage" class="ops-error">{{ errorMessage }}</p>

    <div class="admin-card">
      <div class="card-header">
        <h3>闭环状态</h3>
        <span class="status-badge" :class="closureOk ? 'badge-ok' : 'badge-warn'">
          {{ closureOk ? '就绪' : '待补齐' }}
        </span>
      </div>
      <dl class="card-info">
        <dt>编制缺口</dt>
        <dd>{{ missingCount }}</dd>
        <dt>本地已装</dt>
        <dd>{{ localInstalled }}</dd>
        <dt>远端可达</dt>
        <dd>{{ remoteReachable ? '是' : '否' }}</dd>
      </dl>
      <pre v-if="closureDetail" class="ops-json">{{ closureDetail }}</pre>
    </div>

    <div class="admin-card admin-card--wide">
      <div class="card-header">
        <h3>六线编制概览</h3>
      </div>
      <ul class="dept-list">
        <li v-for="dept in SIX_LINE_DEPARTMENTS" :key="dept.id">
          <strong>{{ dept.label }}</strong>
          <span class="dept-meta">{{ deptCount(dept.id) }} 个编制包</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { api } from '@/api'
import { SIX_LINE_DEPARTMENTS } from '@/constants/sixLineDepartments'
import { buildDutyRosterRows } from '@/utils/dutyRosterEmployeeList'

const loading = ref(false)
const errorMessage = ref('')
const closureOk = ref(false)
const missingCount = ref(0)
const localInstalled = ref(0)
const remoteReachable = ref(false)
const closureDetail = ref('')
const rosterRows = ref<ReturnType<typeof buildDutyRosterRows>>([])

function deptCount(_deptId: string) {
  return Math.ceil(rosterRows.value.length / SIX_LINE_DEPARTMENTS.length)
}

async function refresh() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [closureRes, remoteRes, healthRes] = await Promise.all([
      xcmaxOpsApi.closureStatus(),
      api.get('/api/xcmax/admin/remote-status'),
      xcmaxOpsApi.dutyHealth(),
    ])
    const closureData =
      closureRes && typeof closureRes === 'object' && 'data' in closureRes
        ? (closureRes as { data: Record<string, unknown> }).data
        : (closureRes as Record<string, unknown>)
    const health =
      healthRes && typeof healthRes === 'object' ? (healthRes as Record<string, unknown>) : {}
    rosterRows.value = buildDutyRosterRows(health)
    missingCount.value = rosterRows.value.filter((r) => r.status === 'missing').length
    localInstalled.value = Number(health.planned_local_installed_count ?? 0)
    closureOk.value = missingCount.value === 0 && localInstalled.value > 0
    closureDetail.value = JSON.stringify(closureData ?? {}, null, 2).slice(0, 1200)
    const rd =
      remoteRes && typeof remoteRes === 'object' && 'data' in remoteRes
        ? (remoteRes as { data: Record<string, unknown> }).data
        : remoteRes
    remoteReachable.value =
      rd && typeof rd === 'object' ? (rd as { reachable?: boolean }).reachable === true : false
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refresh()
})
</script>

<style scoped>
.xcmax-admin-infra {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ops-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}
.ops-error {
  color: #b91c1c;
  font-size: 13px;
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
.ops-json {
  margin-top: 10px;
  padding: 10px;
  font-size: 11px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  overflow: auto;
  max-height: 180px;
}
.dept-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.dept-list li {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  padding: 8px 10px;
  background: rgba(24, 144, 255, 0.04);
  border-radius: 8px;
}
.dept-meta {
  color: #64748b;
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
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
}
.btn-secondary {
  background: rgba(24, 144, 255, 0.1);
  color: #1890ff;
}
.btn:disabled {
  opacity: 0.55;
}
</style>
