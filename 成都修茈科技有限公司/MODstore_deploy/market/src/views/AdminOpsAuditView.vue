<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { api } from '../api'

const authStore = useAuthStore()
const { isAdmin } = storeToRefs(authStore)
const route = useRoute()

const loading = ref(false)
const error = ref('')
const items = ref<
  Array<{
    id: number
    employee_id: string
    handler: string
    command_id: string
    exit_code: number | null
    approval_required: boolean
    dry_run: boolean
    duration_ms: number
    created_at: string | null
    stdout_excerpt: string
    stderr_excerpt: string
    error: string
  }>
>([])

const staged = ref<
  Array<{
    id: number
    branch: string
    status: string
    files_changed_count: number
    created_at: string | null
    diff_summary: string
  }>
>([])

const tokens = ref<
  Array<{
    id: number
    kind: string
    token_hash_prefix: string
    authorized_email: string
    expires_at: string | null
    used_at: string | null
    created_at: string | null
  }>
>([])

async function load() {
  if (!isAdmin.value) return
  loading.value = true
  error.value = ''
  try {
    const employeeId = typeof route.query.employee_id === 'string' ? route.query.employee_id.trim() : ''
    const [r, s, t] = await Promise.all([
      api.adminOpsAuditLogs({ limit: 100, employee_id: employeeId || undefined }) as Promise<{ items?: typeof items.value }>,
      api.adminOpsStagedChanges({ limit: 80 }) as Promise<{ items?: typeof staged.value }>,
      api.adminOpsApprovalTokens({ limit: 80 }) as Promise<{ items?: typeof tokens.value }>,
    ])
    items.value = Array.isArray(r?.items) ? r.items : []
    staged.value = Array.isArray(s?.items) ? s.items : []
    tokens.value = Array.isArray(t?.items) ? t.items : []
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
watch(() => route.query.employee_id, () => { void load() })
</script>

<template>
  <div v-if="!isAdmin" class="ops-audit-denied">
    <p>需要管理员权限</p>
    <router-link to="/" class="btn">返回</router-link>
  </div>
  <div v-else class="ops-audit-page">
    <header class="ops-audit-header">
      <h1>运维操作日志</h1>
      <div class="ops-audit-actions">
        <button type="button" class="btn ghost" :disabled="loading" @click="load">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
        <router-link :to="{ name: 'admin-duty-employees' }" class="btn ghost">← 返回值班图</router-link>
        <router-link :to="{ name: 'admin-employee-autonomy' }" class="btn ghost">自治面板</router-link>
        <router-link :to="{ name: 'admin-yuangon-onboard' }" class="btn ghost">Yuangon 上架</router-link>
        <router-link :to="{ name: 'admin-change-requests' }" class="btn ghost">员工变更审批</router-link>
      </div>
    </header>
    <p v-if="error" class="ops-audit-err">{{ error }}</p>

    <h2 class="ops-audit-sub">待审分支（Staged changes）</h2>
    <div class="ops-audit-table-wrap">
      <table class="ops-audit-table">
        <thead>
          <tr>
            <th>id</th>
            <th>分支</th>
            <th>状态</th>
            <th>文件数</th>
            <th>创建时间</th>
            <th>摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in staged" :key="'s' + row.id">
            <td>{{ row.id }}</td>
            <td><code>{{ row.branch }}</code></td>
            <td>{{ row.status }}</td>
            <td>{{ row.files_changed_count }}</td>
            <td class="muted">{{ row.created_at || '—' }}</td>
            <td class="diff-cell">{{ (row.diff_summary || '').slice(0, 200) }}{{ (row.diff_summary || '').length > 200 ? '…' : '' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !staged.length" class="muted">暂无待审记录</p>
    </div>

    <h2 class="ops-audit-sub">审批令牌（仅 hash 前缀）</h2>
    <div class="ops-audit-table-wrap">
      <table class="ops-audit-table">
        <thead>
          <tr>
            <th>id</th>
            <th>kind</th>
            <th>hash 前缀</th>
            <th>授权邮箱</th>
            <th>过期</th>
            <th>已用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in tokens" :key="'t' + row.id">
            <td>{{ row.id }}</td>
            <td><code>{{ row.kind }}</code></td>
            <td><code>{{ row.token_hash_prefix }}</code></td>
            <td>{{ row.authorized_email }}</td>
            <td class="muted">{{ row.expires_at || '—' }}</td>
            <td class="muted">{{ row.used_at || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !tokens.length" class="muted">暂无令牌记录</p>
    </div>

    <h2 class="ops-audit-sub">运维 shell/ssh 审计</h2>
    <div class="ops-audit-table-wrap">
      <table class="ops-audit-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>员工</th>
            <th>handler</th>
            <th>command</th>
            <th>exit</th>
            <th>审批/演练</th>
            <th>ms</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in items" :key="row.id">
            <td class="muted">{{ row.created_at || '—' }}</td>
            <td><code>{{ row.employee_id }}</code></td>
            <td>{{ row.handler }}</td>
            <td><code>{{ row.command_id }}</code></td>
            <td>{{ row.exit_code ?? '—' }}</td>
            <td>
              <span v-if="row.approval_required" class="pill warn">审批</span>
              <span v-if="row.dry_run" class="pill">dry-run</span>
            </td>
            <td>{{ row.duration_ms != null ? Math.round(row.duration_ms) : '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!loading && !items.length" class="muted">暂无记录</p>
    </div>
  </div>
</template>

<style scoped>
.ops-audit-page {
  padding: 1rem 1.25rem;
  max-width: 1200px;
  margin: 0 auto;
}
.ops-audit-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  margin-bottom: 1rem;
}
.ops-audit-header h1 {
  font-size: 1.15rem;
  margin: 0;
}
.ops-audit-sub {
  font-size: 1rem;
  margin: 1.5rem 0 0.5rem;
  font-weight: 600;
}
.diff-cell {
  font-size: 0.72rem;
  max-width: 280px;
  word-break: break-word;
}
.ops-audit-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.btn {
  display: inline-block;
  padding: 0.4rem 0.75rem;
  border-radius: 6px;
  text-decoration: none;
  border: 1px solid var(--color-border-subtle, #444);
  background: var(--color-bg-elevated, #1e1e2e);
  color: var(--color-text-primary, #e0e0e0);
  cursor: pointer;
  font-size: 0.85rem;
}
.btn.ghost {
  background: transparent;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.ops-audit-err {
  color: var(--color-error, #f87171);
  font-size: 0.9rem;
}
.ops-audit-table-wrap {
  overflow-x: auto;
}
.ops-audit-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.ops-audit-table th,
.ops-audit-table td {
  border: 1px solid var(--color-border-subtle, #333);
  padding: 0.35rem 0.5rem;
  text-align: left;
  vertical-align: top;
}
.ops-audit-table th {
  background: rgba(255, 255, 255, 0.04);
}
.muted {
  color: var(--color-text-muted, #888);
}
.pill {
  display: inline-block;
  font-size: 0.7rem;
  padding: 0.1rem 0.35rem;
  border-radius: 4px;
  background: rgba(99, 102, 241, 0.15);
  margin-right: 0.25rem;
}
.pill.warn {
  background: rgba(245, 158, 11, 0.15);
  color: #f59e0b;
}
.ops-audit-denied {
  padding: 2rem;
  text-align: center;
  color: var(--color-text-muted, #888);
}
code {
  font-size: 0.78rem;
  word-break: break-all;
}
html[data-workbench-theme='light'] .btn{background:#fff;color:#1a1a1a;border-color:#d1d5db}
html[data-workbench-theme='light'] .ops-audit-err{color:#dc2626}
html[data-workbench-theme='light'] .ops-audit-table th,html[data-workbench-theme='light'] .ops-audit-table td{border-color:#e2e8f0}
html[data-workbench-theme='light'] .ops-audit-table th{background:#f8f9fa}
html[data-workbench-theme='light'] .muted{color:#94a3b8}
html[data-workbench-theme='light'] .pill{background:rgba(99,102,241,0.08)}
html[data-workbench-theme='light'] .pill.warn{background:rgba(217,119,6,0.08);color:#d97706}
</style>
