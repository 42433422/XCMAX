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
        @click="selectAdminTab(tab.id)"
      >
        {{ tab.label }}
      </button>
    </nav>

    <div v-show="activeTab === 'overview'" class="page-content">
      <div class="page-header">
        <h2>服务器后台总览</h2>
        <div class="header-actions">
          <button class="btn btn-primary" type="button" @click="openDeployModal">
            <i class="fa fa-cloud-upload" aria-hidden="true"></i>
            推送更新包
          </button>
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
            <span
              class="status-badge"
              :class="localStatus.degraded ? 'badge-warn' : localStatus.ok ? 'badge-ok' : 'badge-err'"
            >
              {{ localStatus.degraded ? '降级' : localStatus.ok ? '正常' : '异常' }}
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

        <!-- 软件版本与更新包 -->
        <div class="admin-card admin-card--release">
          <div class="card-header">
            <i class="fa fa-cloud-upload card-icon" aria-hidden="true"></i>
            <h3>软件版本与更新包</h3>
            <span class="status-badge" :class="deployBadgeClass">
              {{ deployBadgeText }}
            </span>
          </div>
          <dl class="card-info">
            <dt>管理端版本</dt><dd>{{ deployStatus?.admin_local?.version || localStatus.version || '—' }}</dd>
            <dt>管理端 Git</dt><dd class="mono small">{{ shortSha(deployStatus?.admin_local?.git_sha) }}</dd>
            <dt>update 站版本</dt><dd>{{ deployStatus?.update_hub?.version || '—' }}</dd>
            <dt>update 站 Git</dt><dd class="mono small">{{ shortSha(deployStatus?.update_hub?.git_sha) }}</dd>
            <dt>企业端</dt>
            <dd>{{ deployStatus?.enterprise?.reachable ? '在线' : '不可达' }}</dd>
          </dl>
          <p class="release-hint" :class="`is-${deployHintKind}`">
            {{ deployHintText }}
          </p>
          <p v-if="deployStatusError" class="release-error">{{ deployStatusError }}</p>
          <div class="card-actions">
            <button class="btn btn-secondary btn-sm" :disabled="deployStatusLoading" @click="loadDeployStatus">
              {{ deployStatusLoading ? '检测中...' : '检测版本' }}
            </button>
            <button class="btn btn-primary btn-sm" @click="openDeployModal">推送更新安装包</button>
          </div>
        </div>

        <!-- 自治健康 -->
        <div class="admin-card">
          <div class="card-header">
            <i class="fa fa-heartbeat card-icon" aria-hidden="true"></i>
            <h3>自治健康</h3>
            <span class="status-badge" :class="autonomyHealth.alive ? 'badge-ok' : 'badge-err'">
              {{ autonomyHealth.alive ? '服务存活' : '不可达' }}
            </span>
          </div>
          <dl class="card-info">
            <dt>审批服务</dt><dd>{{ autonomyHealth.service || '—' }}</dd>
            <dt>最近 loop</dt><dd>{{ autonomyHealth.loopStatus || '—' }}</dd>
            <dt>run_id</dt><dd class="mono small">{{ autonomyHealth.loopRunId || '—' }}</dd>
            <dt>闭环缺口</dt><dd>{{ autonomyHealth.gapCount ?? '—' }}</dd>
          </dl>
          <p v-if="autonomyHealth.error" class="release-error">{{ autonomyHealth.error }}</p>
          <div class="card-actions">
            <button class="btn btn-secondary btn-sm" :disabled="autonomyHealthLoading" @click="loadAutonomyHealth">
              {{ autonomyHealthLoading ? '检测中...' : '刷新自治健康' }}
            </button>
            <button class="btn btn-primary btn-sm" type="button" @click="selectAdminTab('autonomy')">打开自治总览</button>
          </div>
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

    <div
      v-if="mountedTabs.has('autonomy')"
      v-show="activeTab === 'autonomy'"
      class="page-content admin-tab-panel"
    >
      <XCmaxAdminAutonomyTab />
    </div>
    <div
      v-if="mountedTabs.has('infra')"
      v-show="activeTab === 'infra'"
      class="page-content admin-tab-panel"
    >
      <XCmaxAdminInfraTab />
    </div>
    <div
      v-if="mountedTabs.has('duty')"
      v-show="activeTab === 'duty'"
      class="page-content admin-tab-panel"
    >
      <XCmaxAdminDutyTab />
    </div>
    <AdminDeployUpdateModal v-model="deployModalOpen" @done="handleDeployDone" />
  </div>
</template>

<script>
import './XCmaxAdminView.extracted.css'
/** 供 App.vue keep-alive include 匹配，切换侧栏路由时保留总览数据 */
export default { name: 'XCmaxAdminView' }
</script>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import XCmaxAdminInfraTab from '@/components/admin/XCmaxAdminInfraTab.vue'
import XCmaxAdminDutyTab from '@/components/admin/XCmaxAdminDutyTab.vue'
import XCmaxAdminAutonomyTab from '@/components/admin/XCmaxAdminAutonomyTab.vue'
import AdminDeployUpdateModal from '@host/components/admin/AdminDeployUpdateModal.vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'

const adminTabs = [
  { id: 'overview', label: '总览' },
  { id: 'autonomy', label: '自治总览' },
  { id: 'infra', label: '基础设施' },
  { id: 'duty', label: '编制与调度' },
]
const activeTab = ref('overview')
const mountedTabs = ref(new Set(['overview']))
import { api } from '@/api'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { appAlert } from '@/utils/appDialog'
import { getPersonnelModApiBase } from '@/constants/personnelModApi'

const refreshing = ref(false)
const syncing = ref(false)
const syncingEmployees = ref(false)

const localStatus = ref({
  ok: false,
  degraded: false,
  version: '',
  database: '',
  uptime: '',
  address: window.location.host,
})
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
const deployModalOpen = ref(false)
const deployStatus = ref(null)
const deployStatusLoading = ref(false)
const deployStatusError = ref('')
const autonomyHealthLoading = ref(false)
const autonomyHealth = ref({
  alive: false,
  service: '',
  loopStatus: '',
  loopRunId: '',
  gapCount: null,
  error: '',
})
/** 首次进入时拉取；之后依赖缓存与「刷新状态」 */
const overviewBootstrapped = ref(false)

function selectAdminTab(tabId) {
  activeTab.value = tabId
  if (!mountedTabs.value.has(tabId)) {
    mountedTabs.value = new Set([...mountedTabs.value, tabId])
  }
}

async function loadAutonomyHealth() {
  autonomyHealthLoading.value = true
  autonomyHealth.value = { ...autonomyHealth.value, error: '' }
  try {
    const [health, runtime, closure] = await Promise.all([
      xcmaxAdminApi.fetchAutonomyHealth().catch(() => null),
      xcmaxMarketProxy.selfMaintenanceRuntimeStatus(20).catch(() => null),
      xcmaxOpsApi.closureStatus().catch(() => null),
    ])
    const mem = runtime?.memory || {}
    const last = mem.last_run || {}
    const timelines = Array.isArray(runtime?.run_timelines) ? runtime.run_timelines : []
    const latest = timelines[0] || {}
    const closureData = closure?.data || closure || {}
    let gapCount = closureData.gap_count ?? closureData.closure_gap_count ?? null
    if (gapCount == null && Array.isArray(closureData.gaps)) gapCount = closureData.gaps.length
    if (gapCount == null && Array.isArray(closureData.missing_remote)) {
      gapCount = closureData.missing_remote.length
    }
    autonomyHealth.value = {
      alive: Boolean(health?.ok),
      service: health?.service || '',
      loopStatus: last.status || latest.status || runtime?.status || 'unknown',
      loopRunId: last.run_id || latest.run_id || '',
      gapCount,
      error: '',
    }
  } catch (e) {
    autonomyHealth.value = {
      ...autonomyHealth.value,
      alive: false,
      error: e?.message || String(e),
    }
  } finally {
    autonomyHealthLoading.value = false
  }
}

const deployBadgeText = computed(() => {
  if (deployStatusLoading.value) return '检测中'
  if (deployStatusError.value) return '异常'
  const flags = deployStatus.value?.flags || {}
  if (flags.needs_push || flags.needs_pack) return '待推送'
  if (flags.enterprise_pending) return '已推送'
  if (flags.up_to_date) return '最新'
  if (deployStatus.value?.update_hub?.reachable === false) return '未连通'
  return '待检测'
})

const deployBadgeClass = computed(() => {
  if (deployStatusError.value || deployStatus.value?.update_hub?.reachable === false) return 'badge-err'
  const flags = deployStatus.value?.flags || {}
  if (flags.needs_push || flags.needs_pack) return 'badge-warn'
  if (flags.enterprise_pending) return 'badge-info'
  if (flags.up_to_date) return 'badge-ok'
  return 'badge-dim'
})

const deployHintKind = computed(() => {
  const flags = deployStatus.value?.flags || {}
  if (deployStatusError.value) return 'error'
  if (flags.needs_push || flags.needs_pack) return 'warn'
  if (flags.enterprise_pending) return 'info'
  if (flags.up_to_date) return 'ok'
  return 'dim'
})

const deployHintText = computed(() => {
  if (deployStatusError.value) return '版本检测失败，请检查管理端会话或 update 站配置。'
  const flags = deployStatus.value?.flags || {}
  const version = deployStatus.value?.admin_local?.version || deployStatus.value?.update_hub?.version || ''
  if (flags.needs_pack) return `本地 ${version || '当前版本'} 尚未打包，推送时会先生成更新包。`
  if (flags.needs_push) return `本地 ${version || '当前版本'} 比 update 站新，需要推送更新安装包。`
  if (flags.enterprise_pending) return `新版本 ${version || deployStatus.value?.update_hub?.version || ''} 已推送到 update 站，企业端待拉取。`
  if (flags.up_to_date) return `管理端与 update 站已同步${version ? `（${version}）` : ''}。`
  return '点击检测版本，确认本地、update 站和企业端的软件版本。'
})

function sourceLabel(source) {
  const map = { local: '本地 Mod', remote: '服务器', core: '系统内置', employee: '员工包' }
  return map[source] || source || '未知'
}

function shortSha(value) {
  const text = String(value || '').trim()
  if (!text) return '—'
  return text.length > 12 ? text.slice(0, 12) : text
}

function openDeployModal() {
  deployModalOpen.value = true
}

function emitDeployStatusUpdated() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(
    new CustomEvent('xcagi:admin-deploy-updated', {
      detail: {
        text: deployBadgeText.value,
        version:
          deployStatus.value?.update_hub?.version ||
          deployStatus.value?.admin_local?.version ||
          '',
        flags: deployStatus.value?.flags || {},
      },
    }),
  )
}

async function loadDeployStatus() {
  deployStatusLoading.value = true
  deployStatusError.value = ''
  try {
    const r = await xcmaxAdminApi.checkDeployUpdates('stable')
    const data = r?.data && typeof r.data === 'object' ? r.data : null
    if (!data) throw new Error(r?.message || '版本检测失败')
    deployStatus.value = data
    emitDeployStatusUpdated()
  } catch (e) {
    deployStatus.value = null
    deployStatusError.value = e instanceof Error ? e.message : String(e || '版本检测失败')
    emitDeployStatusUpdated()
  } finally {
    deployStatusLoading.value = false
  }
}

async function handleDeployDone() {
  await loadDeployStatus()
}

async function loadLocalStatus() {
  try {
    const r = await api.get('/api/health')
    const status = String(r?.status || r?.data?.status || '').toLowerCase()
    localStatus.value = {
      // 后端 /api/health 使用 status: "healthy"（见 fastapi_routes.__init__），与 "ok" 口径并存
      ok: status === 'ok' || status === 'healthy' || r?.ok === true,
      degraded: status === 'degraded',
      version: r?.version || r?.data?.version || '—',
      database: r?.database || 'ok',
      uptime: r?.uptime || '—',
      address: window.location.host
    }
  } catch {
    localStatus.value.ok = false
    localStatus.value.degraded = false
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
    await Promise.all([
      loadLocalStatus(),
      loadRemoteStatus(),
      loadSyncStatus(),
      loadModules(),
      loadRemoteEmployees(),
      loadDeployStatus(),
      loadAutonomyHealth(),
    ])
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


