<template>
  <div class="duty-roster-panel">
    <div class="panel-toolbar">
      <input
        v-model="filter"
        class="filter-input"
        type="search"
        placeholder="筛选员工包 id…"
        aria-label="筛选编制包"
      />
      <span class="pill">{{ filteredRows.length }} / {{ rows.length }}</span>
    </div>
    <div class="roster-grid">
      <article
        v-for="row in filteredRows"
        :key="row.pkgId"
        class="roster-card"
        :class="`roster-card--${row.status}`"
      >
        <h4 class="mono">{{ row.pkgId }}</h4>
        <span class="status-label">{{ statusLabel(row.status) }}</span>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import { buildDutyRosterRows, type DutyRosterRow } from '@/utils/dutyRosterEmployeeList'

const props = defineProps<{ refreshKey?: number }>()

const filter = ref('')
const rows = ref<DutyRosterRow[]>([])

const filteredRows = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return rows.value
  return rows.value.filter((r) => r.pkgId.toLowerCase().includes(q))
})

function statusLabel(status: DutyRosterRow['status']) {
  const map: Record<DutyRosterRow['status'], string> = {
    installed: '本地已装',
    registered: '已登记',
    missing: '缺岗',
    planned: '计划编制',
  }
  return map[status] || status
}

async function load() {
  const health = await xcmaxOpsApi.dutyHealth()
  const h = health && typeof health === 'object' ? (health as Record<string, unknown>) : {}
  rows.value = buildDutyRosterRows(h)
}

onMounted(() => {
  void load()
})

watch(
  () => props.refreshKey,
  () => {
    void load()
  },
)
</script>

<style scoped>
.duty-roster-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.filter-input {
  flex: 1;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(15, 23, 42, 0.12);
  font-size: 13px;
}
.pill {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #0369a1;
}
.roster-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.roster-card {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: #fff;
}
.roster-card h4 {
  margin: 0 0 6px;
  font-size: 12px;
  word-break: break-all;
}
.roster-card--missing {
  border-color: #fecaca;
  background: #fff8f8;
}
.roster-card--installed {
  border-color: #bbf7d0;
  background: #f0fdf4;
}
.roster-card--registered {
  border-color: #bae6fd;
  background: #f0f9ff;
}
.status-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
}
.mono {
  font-family: ui-monospace, monospace;
}
</style>
