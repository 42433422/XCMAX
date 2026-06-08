<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from '../i18n'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

const { t } = useI18n()
const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)

type Row = {
  id: number
  source_employee_id: string
  change_kind: string
  diff_summary: string
  diff_blob: string
  status: string
  risk_level: string
  created_at: string | null
  target_paths: string[]
}

const loading = ref(false)
const error = ref('')
const items = ref<Row[]>([])
const selected = ref<Row | null>(null)
const drawerOpen = ref(false)
const statusFilter = ref('pending')
const approveExtras = ref<{
  git_suggestions?: string[]
  post_apply_pytest?: Record<string, unknown>
} | null>(null)

async function load() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  try {
    const r = (await api.adminChangeRequestsList({
      status: statusFilter.value || undefined,
      limit: 100,
    })) as { items?: Row[] }
    items.value = Array.isArray(r?.items) ? r.items : []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function openDetail(row: Row) {
  selected.value = row
  drawerOpen.value = true
}

function closeDrawer() {
  drawerOpen.value = false
  selected.value = null
}

function formatBlob(blob: string): string {
  const s = blob || ''
  if (s.length > 12000) return `${s.slice(0, 12000)}\n…`
  return s
}

async function approve() {
  if (!selected.value) return
  loading.value = true
  error.value = ''
  approveExtras.value = null
  try {
    const r = (await api.adminChangeRequestApprove(selected.value.id)) as {
      git_suggestions?: string[]
      post_apply_pytest?: Record<string, unknown>
    }
    approveExtras.value = {
      git_suggestions: Array.isArray(r?.git_suggestions) ? r.git_suggestions : [],
      post_apply_pytest: r?.post_apply_pytest && typeof r.post_apply_pytest === 'object' ? r.post_apply_pytest : undefined,
    }
    closeDrawer()
    await load()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function reject() {
  if (!selected.value) return
  const reason = window.prompt(t('admin.changeRequests.rejectPrompt'), '') || ''
  loading.value = true
  error.value = ''
  try {
    await api.adminChangeRequestReject(selected.value.id, { reason })
    closeDrawer()
    await load()
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div v-if="!isAdmin" class="page-denied">
    <p>{{ t('admin.accessDenied') }}</p>
    <router-link to="/" class="btn">{{ t('common.back') }}</router-link>
  </div>
  <div v-else class="cr-page">
    <header class="cr-header">
      <h1>{{ t('admin.changeRequests.title') }}</h1>
      <div class="cr-actions">
        <label class="cr-filter">
          <span>{{ t('admin.changeRequests.status') }}</span>
          <select v-model="statusFilter" @change="load">
            <option value="">{{ t('admin.changeRequests.all') }}</option>
            <option value="pending">pending</option>
            <option value="applied">applied</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
        <button type="button" class="btn ghost" :disabled="loading" @click="load">
          {{ loading ? '…' : t('common.refresh') }}
        </button>
        <router-link :to="{ name: 'admin-yuangon-onboard' }" class="btn ghost">{{ t('admin.yuangonOnboard.title') }}</router-link>
        <router-link :to="{ name: 'admin-employee-autonomy' }" class="btn ghost">自治面板</router-link>
        <router-link :to="{ name: 'admin-ops-audit' }" class="btn ghost">{{ t('admin.changeRequests.backOps') }}</router-link>
      </div>
    </header>
    <p v-if="error" class="cr-err">{{ error }}</p>

    <section v-if="approveExtras" class="cr-extras">
      <h2 class="cr-extras-title">{{ t('admin.changeRequests.approveGitTitle') }}</h2>
      <pre v-if="approveExtras.git_suggestions?.length" class="cr-pre cr-pre--compact">{{ (approveExtras.git_suggestions || []).join('\n') }}</pre>
      <p v-else class="muted">—</p>
      <h2 class="cr-extras-title">{{ t('admin.changeRequests.approveCiTitle') }}</h2>
      <pre class="cr-pre cr-pre--compact">{{ JSON.stringify(approveExtras.post_apply_pytest ?? {}, null, 2) }}</pre>
      <button type="button" class="btn ghost cr-extras-dismiss" @click="approveExtras = null">{{ t('admin.changeRequests.dismissApproveExtras') }}</button>
    </section>

    <div class="cr-table-wrap">
      <table class="cr-table">
        <thead>
          <tr>
            <th>id</th>
            <th>{{ t('admin.changeRequests.employee') }}</th>
            <th>kind</th>
            <th>status</th>
            <th>risk</th>
            <th>{{ t('admin.changeRequests.created') }}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td>{{ row.id }}</td>
            <td><code>{{ row.source_employee_id }}</code></td>
            <td>{{ row.change_kind }}</td>
            <td><span class="pill">{{ row.status }}</span></td>
            <td>{{ row.risk_level }}</td>
            <td class="muted">{{ row.created_at || '—' }}</td>
            <td>
              <button type="button" class="btn link" @click="openDetail(row)">{{ t('admin.changeRequests.detail') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !items.length" class="muted">{{ t('admin.changeRequests.empty') }}</p>
    </div>

    <div v-if="drawerOpen && selected" class="cr-drawer-backdrop" @click.self="closeDrawer">
      <aside class="cr-drawer">
        <header class="cr-drawer-head">
          <h2>#{{ selected.id }} · {{ selected.source_employee_id }}</h2>
          <button type="button" class="btn ghost" @click="closeDrawer">×</button>
        </header>
        <p class="muted">{{ selected.diff_summary }}</p>
        <pre class="cr-pre">{{ formatBlob(selected.diff_blob) }}</pre>
        <div v-if="selected.status === 'pending'" class="cr-drawer-actions">
          <button type="button" class="btn primary" :disabled="loading" @click="approve">{{ t('admin.changeRequests.approve') }}</button>
          <button type="button" class="btn ghost" :disabled="loading" @click="reject">{{ t('admin.changeRequests.reject') }}</button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.cr-page {
  padding: 1rem 1.25rem;
  max-width: 1200px;
  margin: 0 auto;
}
.cr-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.cr-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
}
.cr-filter {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.9rem;
}
.cr-err {
  color: #c44;
  margin-bottom: 0.75rem;
}
.cr-extras {
  margin-bottom: 1rem;
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid rgba(127, 127, 127, 0.25);
  background: rgba(127, 127, 127, 0.06);
}
.cr-extras-title {
  font-size: 0.95rem;
  margin: 0.75rem 0 0.35rem;
}
.cr-extras-title:first-child {
  margin-top: 0;
}
.cr-pre--compact {
  max-height: 14rem;
  margin: 0;
}
.cr-extras-dismiss {
  margin-top: 0.75rem;
}
.cr-table-wrap {
  overflow-x: auto;
}
.cr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}
.cr-table th,
.cr-table td {
  border-bottom: 1px solid rgba(127, 127, 127, 0.25);
  padding: 0.45rem 0.5rem;
  text-align: left;
  vertical-align: top;
}
.muted {
  color: rgba(127, 127, 127, 0.95);
}
.pill {
  display: inline-block;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: rgba(127, 127, 127, 0.15);
  font-size: 0.8rem;
}
.btn.link {
  background: none;
  border: none;
  color: var(--color-primary, #6ea8fe);
  cursor: pointer;
  padding: 0;
}
.cr-drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 40;
  display: flex;
  justify-content: flex-end;
}
.cr-drawer {
  width: min(560px, 100%);
  background: var(--color-bg-elevated, #1e1e1e);
  color: inherit;
  padding: 1rem;
  overflow-y: auto;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.25);
}
.cr-drawer-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}
.cr-pre {
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.78rem;
  max-height: 55vh;
  overflow: auto;
  background: rgba(127, 127, 127, 0.08);
  padding: 0.75rem;
  border-radius: 6px;
}
.cr-drawer-actions {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
}
.page-denied {
  padding: 2rem;
  text-align: center;
}
.btn {
  display: inline-flex;
  align-items: center;
  padding: 0.35rem 0.75rem;
  border-radius: 6px;
  border: 1px solid rgba(127, 127, 127, 0.35);
  text-decoration: none;
  cursor: pointer;
  font-size: 0.9rem;
}
.btn.primary {
  background: var(--color-primary, #3b82f6);
  color: #fff;
  border-color: transparent;
}
.btn.ghost {
  background: transparent;
}
html[data-workbench-theme='light'] .cr-err{color:#dc2626}
html[data-workbench-theme='light'] .cr-extras{background:rgba(0,0,0,0.03);border-color:#e2e8f0}
html[data-workbench-theme='light'] .cr-table th,html[data-workbench-theme='light'] .cr-table td{border-color:#e2e8f0}
html[data-workbench-theme='light'] .muted{color:#94a3b8}
html[data-workbench-theme='light'] .pill{background:rgba(0,0,0,0.06)}
html[data-workbench-theme='light'] .btn.link{color:#2563eb}
html[data-workbench-theme='light'] .cr-drawer-backdrop{background:rgba(0,0,0,0.2)}
html[data-workbench-theme='light'] .cr-drawer{background:#fff;color:#1a1a1a}
html[data-workbench-theme='light'] .cr-pre{background:rgba(0,0,0,0.04)}
html[data-workbench-theme='light'] .btn{border-color:#d1d5db}
html[data-workbench-theme='light'] .btn.primary{background:#3b82f6;color:#fff}
</style>
