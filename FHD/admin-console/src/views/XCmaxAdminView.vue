<template>
  <div class="xcmax-admin-view" id="view-xcmax-admin">
    <nav class="admin-tab-bar" role="tablist" aria-label="服务器后台分区">
      <button
        v-for="tab in adminTabs"
        :key="tab.id"
        type="button"
        role="tab"
        class="admin-tab"
        :class="{ active: activeTab === tab.id }"
        :aria-selected="activeTab === tab.id"
        @click="activeTab = tab.id"
      >
        {{ tab.label }}
      </button>
    </nav>

    <div v-show="activeTab === 'overview'" class="page-content">
      <div class="page-header">
        <h2>服务器后台总览</h2>
        <div class="header-actions">
          <button class="btn btn-secondary" :disabled="refreshing" @click="refreshAll">
            <i class="fa fa-refresh" :class="{ 'fa-spin': refreshing }" aria-hidden="true"></i>
            {{ refreshing ? '刷新中...' : '刷新状态' }}
          </button>
        </div>
      </div>

      <div class="admin-grid">
        <!-- 本地节点 -->
        <div class="admin-card">
          <div class="card-header">
            <i class="fa fa-desktop card-icon" aria-hidden="true"></i>
            <h3>本地节点</h3>
            <span class="status-badge" :class="localStatus.ok ? 'badge-ok' : 'badge-err'">
              {{ localStatus.ok ? '正常' : '异常' }}
            </span>
          </div>
          <dl class="card-info">
            <dt>版本</dt><dd>{{ localStatus.version || '—' }}</dd>
            <dt>数据库</dt><dd>{{ localStatus.database || '—' }}</dd>
            <dt>运行时间</dt><dd>{{ localStatus.uptime || '—' }}</dd>
            <dt>本地地址</dt><dd>{{ localStatus.address }}</dd>
          </dl>
        </div>

        <!-- 远端服务器 -->
        <div class="admin-card">
          <div class="card-header">
            <i class="fa fa-server card-icon" aria-hidden="true"></i>
            <h3>远端服务器</h3>
            <span class="status-badge" :class="remoteStatus.reachable ? 'badge-ok' : 'badge-warn'">
              {{ remoteStatus.reachable ? '在线' : '离线' }}
            </span>
          </div>
          <dl class="card-info">
            <dt>地址</dt><dd>{{ remoteStatus.address || '—' }}</dd>
            <dt>延迟</dt><dd>{{ remoteStatus.latencyMs != null ? `${remoteStatus.latencyMs} ms` : '—' }}</dd>
            <dt>版本</dt><dd>{{ remoteStatus.version || '—' }}</dd>
            <dt>部署时间</dt><dd>{{ remoteStatus.deployTime || '—' }}</dd>
          </dl>
        </div>

        <!-- 同步状态 -->
        <div class="admin-card">
          <div class="card-header">
            <i class="fa fa-refresh card-icon" aria-hidden="true"></i>
            <h3>双向同步</h3>
            <span class="status-badge" :class="syncStatus.healthy ? 'badge-ok' : 'badge-warn'">
              {{ syncStatus.healthy ? '同步中' : '待同步' }}
            </span>
          </div>
          <dl class="card-info">
            <dt>本地游标</dt><dd>{{ syncStatus.localCursor ?? '—' }}</dd>
            <dt>服务器游标</dt><dd>{{ syncStatus.remoteCursor ?? '—' }}</dd>
            <dt>待发送</dt><dd>{{ syncStatus.outboxCount ?? 0 }} 条</dd>
            <dt>最近同步</dt><dd>{{ syncStatus.lastSyncAt || '—' }}</dd>
            <dt>冲突数</dt><dd>{{ syncStatus.conflictCount ?? 0 }}</dd>
          </dl>
          <div class="card-actions">
            <button class="btn btn-primary btn-sm" :disabled="syncing || !remoteStatus.reachable" @click="triggerPush">
              {{ syncing ? '推送中...' : '推送本地变更' }}
            </button>
            <button class="btn btn-secondary btn-sm" :disabled="syncing || !remoteStatus.reachable" @click="triggerPull">
              拉取服务器变更
            </button>
          </div>
        </div>

        <!-- 模块注册 -->
        <div class="admin-card admin-card--wide">
          <div class="card-header">
            <i class="fa fa-puzzle-piece card-icon" aria-hidden="true"></i>
            <h3>模块注册表</h3>
            <span class="status-badge badge-info">{{ modules.length }} 个模块</span>
          </div>
          <table class="module-table" v-if="modules.length">
            <thead>
              <tr>
                <th>模块 ID</th>
                <th>名称</th>
                <th>版本</th>
                <th>来源</th>
                <th>状态</th>
                <th>同步范围</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mod in modules" :key="mod.module_id">
                <td class="mono">{{ mod.module_id }}</td>
                <td>{{ mod.display_name }}</td>
                <td class="mono">{{ mod.version || '—' }}</td>
                <td>
                  <span class="source-badge" :class="`source-${mod.source}`">{{ sourceLabel(mod.source) }}</span>
                </td>
                <td>
                  <span class="status-badge" :class="mod.active ? 'badge-ok' : 'badge-dim'">
                    {{ mod.active ? '启用' : '禁用' }}
                  </span>
                </td>
                <td class="mono small">{{ mod.sync_scope || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-hint">暂无已注册模块，刷新或检查后端 /api/xcmax/admin/modules</p>
        </div>

        <!-- 远端员工 (yuangon) -->
        <div class="admin-card admin-card--wide">
          <div class="card-header">
            <i class="fa fa-users card-icon" aria-hidden="true"></i>
            <h3>远端服务器员工 (yuangon)</h3>
            <span class="status-badge badge-info">{{ remoteEmployees.length }} 名</span>
          </div>
          <div class="card-actions" style="margin-bottom:12px">
            <button class="btn btn-secondary btn-sm" :disabled="syncingEmployees" @click="syncEmployees">
              {{ syncingEmployees ? '同步中...' : '同步服务器员工' }}
            </button>
          </div>
          <table class="module-table" v-if="remoteEmployees.length">
            <thead>
              <tr><th>ID</th><th>名称</th><th>职能域</th><th>区域</th><th>版本</th></tr>
            </thead>
            <tbody>
              <tr v-for="emp in remoteEmployees" :key="emp.employee_id">
                <td class="mono small">{{ emp.employee_id }}</td>
                <td>{{ emp.name }}</td>
                <td class="small">{{ emp.domain || '—' }}</td>
                <td>{{ emp.area || '—' }}</td>
                <td class="mono">{{ emp.version || '—' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-hint">暂无远端员工信息，点击上方按钮同步</p>
        </div>

        <!-- 冲突列表 -->
        <div class="admin-card admin-card--wide" v-if="syncStatus.conflictCount > 0">
          <div class="card-header">
            <i class="fa fa-exclamation-circle card-icon" style="color:#d97706" aria-hidden="true"></i>
            <h3>同步冲突</h3>
            <span class="status-badge badge-warn">{{ syncStatus.conflictCount }} 条待处理</span>
          </div>
          <div class="card-actions" style="margin-bottom:12px">
            <button class="btn btn-secondary btn-sm" @click="loadConflicts">刷新冲突列表</button>
          </div>
          <table class="module-table" v-if="conflicts.length">
            <thead>
              <tr><th>ID</th><th>实体类型</th><th>实体 ID</th><th>操作</th><th>冲突说明</th><th>收到时间</th><th>处理</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in conflicts" :key="c.id">
                <td class="mono">{{ c.id }}</td>
                <td>{{ c.entity_type }}</td>
                <td class="mono small">{{ c.entity_id }}</td>
                <td>{{ c.operation }}</td>
                <td class="small">{{ c.conflict_note || '—' }}</td>
                <td class="small">{{ c.received_at }}</td>
                <td>
                  <button class="btn btn-sm btn-primary" @click="resolveConflict(c.id,'apply')">应用</button>
                  &nbsp;
                  <button class="btn btn-sm btn-secondary" @click="resolveConflict(c.id,'skip')">跳过</button>
                </td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty-hint">点击「刷新冲突列表」加载详情</p>
        </div>

        <!-- 最近错误 -->
        <div class="admin-card admin-card--wide" v-if="recentErrors.length">
          <div class="card-header">
            <i class="fa fa-exclamation-triangle card-icon" aria-hidden="true"></i>
            <h3>最近错误</h3>
            <span class="status-badge badge-err">{{ recentErrors.length }}</span>
          </div>
          <ul class="error-list">
            <li v-for="(err, i) in recentErrors" :key="i" class="error-item">
              <span class="error-time">{{ err.time }}</span>
              <span class="error-msg">{{ err.message }}</span>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <div v-show="activeTab === 'infra'" class="page-content admin-tab-panel">
      <XCmaxAdminInfraTab />
    </div>
    <div v-show="activeTab === 'duty'" class="page-content admin-tab-panel">
      <XCmaxAdminDutyTab />
    </div>
    <div v-show="activeTab === 'automation-policy'" class="page-content admin-tab-panel">
      <div class="page-header">
        <h2>自动化方针</h2>
      </div>
      <XcmaxDashboardEmbed :src="automationEmbedUrl" title="自动化方针" />
    </div>
    <div v-show="activeTab === 'duty-time-architecture'" class="page-content admin-tab-panel">
      <div class="page-header">
        <h2>同时完成时间架构</h2>
      </div>
      <XcmaxDashboardEmbed :src="timeArchEmbedUrl" title="同时完成时间架构" />
    </div>
  </div>
</template>

<script>
/** 供 App.vue keep-alive include 匹配，切换侧栏路由时保留总览数据 */
export default { name: 'XCmaxAdminView' }
</script>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import XCmaxAdminInfraTab from '@/components/admin/XCmaxAdminInfraTab.vue'
import XCmaxAdminDutyTab from '@/components/admin/XCmaxAdminDutyTab.vue'
import XcmaxDashboardEmbed from '@/components/admin/XcmaxDashboardEmbed.vue'
import {
  xcmaxAutomationPolicyEmbedUrl,
  xcmaxDutyTimeArchitectureEmbedUrl,
} from '@/constants/xcmaxDashboardEmbed'

const adminTabs = [
  { id: 'overview', label: '总览' },
  { id: 'infra', label: '基础设施' },
  { id: 'duty', label: '编制与调度' },
  { id: 'automation-policy', label: '自动化方针' },
  { id: 'duty-time-architecture', label: '同时完成时间架构' },
]
const activeTab = ref('overview')
const automationEmbedUrl = xcmaxAutomationPolicyEmbedUrl()
const timeArchEmbedUrl = xcmaxDutyTimeArchitectureEmbedUrl()
import { api } from '@/api'
import { appAlert } from '@/utils/appDialog'
import { getPersonnelModApiBase } from '@/constants/personnelModApi'

const refreshing = ref(false)
const syncing = ref(false)
const syncingEmployees = ref(false)

const localStatus = ref({ ok: false, version: '', database: '', uptime: '', address: window.location.host })
const remoteStatus = ref({
  reachable: false,
  latencyMs: null,
  version: '',
  deployTime: '',
  /** 与 ``/api/xcmax/admin/remote-status`` 返回的 host:port 一致，避免与后端 XCMAX_REMOTE_* 漂移 */
  address: '',
})
const syncStatus = ref({ healthy: false, localCursor: null, remoteCursor: null, outboxCount: 0, lastSyncAt: '', conflictCount: 0 })
const modules = ref([])
const remoteEmployees = ref([])
const recentErrors = ref([])
const conflicts = ref([])
/** 首次进入时拉取；之后依赖缓存与「刷新状态」 */
const overviewBootstrapped = ref(false)

function sourceLabel(source) {
  const map = { local: '本地 Mod', remote: '服务器', core: '系统内置', employee: '员工包' }
  return map[source] || source || '未知'
}

async function loadLocalStatus() {
  try {
    const r = await api.get('/api/health')
    localStatus.value = {
      // 后端 /api/health 使用 status: "healthy"（见 fastapi_routes.__init__），与 "ok" 口径并存
      ok: r?.status === 'ok' || r?.status === 'healthy' || r?.ok === true,
      version: r?.version || r?.data?.version || '—',
      database: r?.database || 'ok',
      uptime: r?.uptime || '—',
      address: window.location.host
    }
  } catch {
    localStatus.value.ok = false
  }
}

async function loadRemoteStatus() {
  const t0 = Date.now()
  try {
    const r = await api.get('/api/xcmax/admin/remote-status')
    const d = r?.data && typeof r.data === 'object' ? r.data : r
    const reachable = d?.reachable === true
    const serverMs = d?.latency_ms
    const host = d?.host != null && d.host !== '' ? String(d.host) : ''
    const port = d?.port != null && d.port !== '' ? String(d.port) : ''
    const address = host && port ? `${host}:${port}` : host || '—'
    remoteStatus.value = {
      reachable,
      // 离线时后端 latency_ms 为 null；不要用「本接口总耗时」冒充远端延迟（会显示上万 ms）
      latencyMs:
        reachable && typeof serverMs === 'number' && !Number.isNaN(serverMs)
          ? serverMs
          : reachable
            ? Math.round(Date.now() - t0)
            : null,
      version: d?.version || '—',
      deployTime: d?.deploy_time || '—',
      address,
    }
  } catch {
    remoteStatus.value = {
      reachable: false,
      latencyMs: null,
      version: '—',
      deployTime: '—',
      address: '—',
    }
  }
}

async function loadSyncStatus() {
  try {
    const r = await api.get('/api/xcmax/sync/status')
    if (r?.success && r?.data) {
      const d = r.data
      syncStatus.value = {
        healthy: d.healthy === true,
        localCursor: d.local_cursor ?? null,
        remoteCursor: d.remote_cursor ?? null,
        outboxCount: d.outbox_count ?? 0,
        lastSyncAt: d.last_sync_at || '—',
        conflictCount: d.conflict_count ?? 0
      }
    }
  } catch {
    /* not yet wired up */
  }
}

async function loadModules() {
  try {
    const r = await api.get('/api/xcmax/admin/modules')
    if (r?.success && Array.isArray(r.data)) {
      modules.value = r.data
    }
  } catch {
    modules.value = []
  }
}

async function loadRemoteEmployees() {
  try {
    const base = getPersonnelModApiBase()
    const r = await api.get(`${base}/employees`, { page: 1, page_size: 200, search: '' })
    if (r?.success && r?.data?.items) {
      remoteEmployees.value = r.data.items.map(e => ({
        employee_id: e.employee_no || e.user_id || e.id,
        name: e.employee_name,
        domain: e.position,
        area: e.department,
        version: ''
      }))
    }
  } catch {
    remoteEmployees.value = []
  }
}

async function syncEmployees() {
  if (syncingEmployees.value) return
  syncingEmployees.value = true
  try {
    const res = await api.post(`${getPersonnelModApiBase()}/employees/sync-remote-yuangon`, {})
    if (!res?.success) throw new Error(res?.message || '同步失败')
    const d = res.data || {}
    await appAlert(`同步完成：${d.employees || 0} 名员工，${d.departments || 0} 个分组`)
    await loadRemoteEmployees()
  } catch (e) {
    recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `同步员工失败: ${e.message}` })
    await appAlert('同步员工失败: ' + (e.message || '未知错误'))
  } finally {
    syncingEmployees.value = false
  }
}

async function triggerPush() {
  if (syncing.value) return
  syncing.value = true
  try {
    const res = await api.post('/api/xcmax/sync/push', {})
    if (res?.success) {
      const d = res.data || {}
      await loadSyncStatus()
      await appAlert(`推送完成：发送 ${d.sent ?? 0} 条，失败 ${d.failed ?? 0} 条`)
    }
  } catch (e) {
    recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `同步推送失败: ${e.message}` })
    await appAlert('推送失败: ' + (e.message || '未知错误'))
  } finally {
    syncing.value = false
  }
}

async function triggerPull() {
  if (syncing.value) return
  syncing.value = true
  try {
    const res = await api.post('/api/xcmax/sync/pull', {})
    if (res?.success) {
      const d = res.data || {}
      await loadSyncStatus()
      await appAlert(`拉取完成：获取 ${d.pull?.pulled ?? 0} 条，应用 ${d.apply?.applied ?? 0} 条，冲突 ${d.apply?.conflicts ?? 0} 条`)
    }
  } catch (e) {
    recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `拉取失败: ${e.message}` })
    await appAlert('拉取失败: ' + (e.message || '未知错误'))
  } finally {
    syncing.value = false
  }
}

async function loadConflicts() {
  try {
    const r = await api.get('/api/xcmax/sync/conflicts', { limit: 50 })
    if (r?.success) conflicts.value = r.data || []
  } catch { conflicts.value = [] }
}

async function resolveConflict(id, action) {
  try {
    const res = await api.post(`/api/xcmax/sync/conflicts/${id}/resolve`, { action })
    if (res?.success) {
      conflicts.value = conflicts.value.filter(c => c.id !== id)
      await loadSyncStatus()
    }
  } catch (e) {
    recentErrors.value.unshift({ time: new Date().toLocaleTimeString(), message: `解决冲突失败: ${e.message}` })
  }
}

async function refreshAll() {
  refreshing.value = true
  try {
    await Promise.all([loadLocalStatus(), loadRemoteStatus(), loadSyncStatus(), loadModules(), loadRemoteEmployees()])
    if (syncStatus.value.conflictCount > 0) await loadConflicts()
  } finally {
    refreshing.value = false
  }
}

let syncEventSource = null
let syncStreamReconnectTimer = null
let syncStreamReconnectDelay = 3000
let syncStreamActive = false
let syncStreamCreatedAt = 0

function startSyncStream() {
  if (syncEventSource) return
  syncStreamActive = true
  const cursorParam = syncStatus.value.localCursor ?? 0
  const url = `/api/xcmax/sync/stream?since_cursor=${cursorParam}`
  syncEventSource = new EventSource(url)
  syncStreamCreatedAt = Date.now()
  syncEventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data?.type === 'connected') {
        syncStreamReconnectDelay = 3000
      }
      if (data?.type === 'heartbeat' && data?.status) {
        const s = data.status
        syncStatus.value = {
          healthy: s.healthy === true,
          localCursor: s.local_cursor ?? syncStatus.value.localCursor,
          remoteCursor: s.remote_cursor ?? syncStatus.value.remoteCursor,
          outboxCount: s.outbox_count ?? 0,
          lastSyncAt: s.last_sync_at || syncStatus.value.lastSyncAt,
          conflictCount: s.conflict_count ?? 0,
        }
      }
    } catch (_) {}
  }
  syncEventSource.onerror = () => {
    const es = syncEventSource
    syncEventSource = null
    if (es) {
      try { es.close() } catch (_) {}
    }
    if (!syncStreamActive) return
    if (syncStreamReconnectTimer != null) return
    syncStreamReconnectTimer = window.setTimeout(() => {
      syncStreamReconnectTimer = null
      if (syncStreamActive) startSyncStream()
    }, syncStreamReconnectDelay)
    syncStreamReconnectDelay = Math.min(syncStreamReconnectDelay * 2, 30000)
  }
}

function stopSyncStream() {
  syncStreamActive = false
  if (syncStreamReconnectTimer != null) {
    clearTimeout(syncStreamReconnectTimer)
    syncStreamReconnectTimer = null
  }
  const age = Date.now() - syncStreamCreatedAt
  if (age < 2000 && syncEventSource) {
    const es = syncEventSource
    syncEventSource = null
    setTimeout(() => { try { es.close() } catch (_) {} }, 500)
  } else {
    syncEventSource?.close()
    syncEventSource = null
  }
}

async function bootstrapOverview() {
  if (!overviewBootstrapped.value) {
    await refreshAll()
    overviewBootstrapped.value = true
  }
}

onMounted(async () => {
  await bootstrapOverview()
  startSyncStream()
})

onActivated(async () => {
  await bootstrapOverview()
  startSyncStream()
})

onDeactivated(() => {
  stopSyncStream()
})

onBeforeUnmount(() => {
  stopSyncStream()
})
</script>

<style scoped>
.xcmax-admin-view {
  overflow-y: auto;
  background: linear-gradient(135deg, #edf5fb 0%, #e7eef6 100%);
}

.page-content {
  padding: 24px 28px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  flex-wrap: wrap;
  gap: 12px;
}

.page-header h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #172033;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.admin-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

.admin-card {
  background: rgba(255, 255, 255, 0.92);
  border-radius: 16px;
  border: 1px solid rgba(15, 76, 129, 0.1);
  box-shadow: 0 4px 18px rgba(15, 76, 129, 0.07);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.admin-card--wide {
  grid-column: 1 / -1;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #172033;
  flex: 1;
}

.card-icon {
  font-size: 18px;
  color: #1890ff;
  width: 22px;
  text-align: center;
}

.card-info {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 14px;
  margin: 0;
  font-size: 13px;
}

.card-info dt {
  color: rgba(23, 32, 51, 0.55);
  font-weight: 600;
  white-space: nowrap;
}

.card-info dd {
  margin: 0;
  color: #172033;
  word-break: break-all;
}

.card-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.badge-ok { background: #e6f9f0; color: #10b759; }
.badge-warn { background: #fff7e0; color: #d97706; }
.badge-err { background: #fff1f0; color: #e53e3e; }
.badge-info { background: #e8f3ff; color: #1890ff; }
.badge-dim { background: #f0f0f0; color: #888; }

.module-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.module-table th {
  text-align: left;
  padding: 8px 10px;
  background: rgba(24, 144, 255, 0.06);
  color: rgba(23, 32, 51, 0.65);
  font-weight: 700;
  font-size: 12px;
  border-bottom: 1px solid rgba(15, 76, 129, 0.1);
}

.module-table td {
  padding: 8px 10px;
  border-bottom: 1px solid rgba(15, 76, 129, 0.06);
  color: #172033;
  vertical-align: middle;
}

.module-table tr:last-child td {
  border-bottom: none;
}

.source-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
}

.source-local { background: #f0f5ff; color: #2563eb; }
.source-remote { background: #f0fdf4; color: #16a34a; }
.source-core { background: #faf5ff; color: #7c3aed; }
.source-employee { background: #fff7ed; color: #c2410c; }

.error-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.error-item {
  display: flex;
  gap: 12px;
  font-size: 13px;
  padding: 8px 12px;
  background: #fff8f8;
  border-radius: 8px;
  border-left: 3px solid #e53e3e;
}

.error-time {
  color: rgba(23, 32, 51, 0.5);
  white-space: nowrap;
  font-size: 12px;
}

.error-msg { color: #172033; }

.empty-hint {
  text-align: center;
  color: rgba(23, 32, 51, 0.45);
  font-size: 13px;
  padding: 20px 0;
  margin: 0;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: opacity 0.15s;
}

.btn:disabled { opacity: 0.55; cursor: not-allowed; }

.btn-sm { padding: 5px 12px; font-size: 12px; }

.btn-primary { background: #1890ff; color: #fff; }
.btn-primary:not(:disabled):hover { background: #096dd9; }

.btn-secondary { background: rgba(24, 144, 255, 0.1); color: #1890ff; }
.btn-secondary:not(:disabled):hover { background: rgba(24, 144, 255, 0.18); }

.mono { font-family: 'Consolas', monospace; font-size: 12px; }
.small { font-size: 12px; }

.admin-tab-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 12px 16px 0;
  border-bottom: 1px solid #e8edf5;
  background: #f8fafc;
}

.admin-tab {
  padding: 8px 14px;
  border: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: #64748b;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.admin-tab.active {
  background: #fff;
  color: #1890ff;
  box-shadow: 0 -1px 0 #1890ff inset;
}

.admin-tab-panel {
  padding-top: 8px;
}
</style>
