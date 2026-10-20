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
        <h3>岗位与服务状态</h3>
        <span class="status-badge" :class="closureOk ? 'badge-ok' : 'badge-warn'">
          {{ closureOk ? '编制就绪' : '存在编制缺口' }}
        </span>
      </div>
      <dl class="card-info">
        <dt>计划岗位</dt>
        <dd>{{ plannedCount }}</dd>
        <dt>缺口岗位</dt>
        <dd>{{ missingCount }}</dd>
        <dt>本机已安装</dt>
        <dd>{{ localInstalled }}</dd>
        <dt>远端服务</dt>
        <dd>{{ remoteStateLabel }}</dd>
      </dl>
      <details v-if="closureDetail"><summary>查看原始状态数据</summary><pre class="ops-json">{{ closureDetail }}</pre></details>
    </div>

    <div class="admin-card admin-card--wide">
      <div class="card-header">
        <h3>计划编制部门（非运行人数）</h3>
      </div>
      <ul class="dept-list">
        <li v-for="(dept, id) in YUANGON_AREAS" :key="id">
          <strong>{{ dept.label }}</strong>
          <span class="dept-meta">{{ dept.ids.length }} 个计划岗位 · 本机已装 {{ departmentCount(dept.ids, 'installed') }} · 缺口 {{ departmentCount(dept.ids, 'missing') }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { api } from '@/api'
import { YUANGON_AREAS } from '@/domain/yuangonDutyRoster'
import { buildDutyRosterRows } from '@/utils/dutyRosterEmployeeList'

const loading = ref(false)
const errorMessage = ref('')
const closureOk = ref(false)
const missingCount = ref(0)
const localInstalled = ref(0)
const remoteReachable = ref(false)
const closureDetail = ref('')
const rosterRows = ref<ReturnType<typeof buildDutyRosterRows>>([])
const plannedCount = computed(() => Object.values(YUANGON_AREAS).reduce((total, dept) => total + dept.ids.length, 0))
const remoteStateLabel = computed(() => loading.value ? '读取中' : errorMessage.value ? '待核实' : remoteReachable.value ? '可达' : '不可达')
const departmentCount = (ids: string[], status: string) => ids.filter(id => rosterRows.value.some(row => row.pkgId === id && row.status === status)).length

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
    rosterRows.value = buildDutyRosterRows({ ...health, ...closureData })
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
.ops-json { margin-top: 10px; padding: 10px; font-size: 11px; background: #0f172a; color: #e2e8f0; border-radius: 6px; overflow: auto; max-height: 180px; }
.dept-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.dept-list li {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
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
