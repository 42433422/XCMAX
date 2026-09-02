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

        <AdminReleaseStatusCard
          ref="releaseStatusCard"
          :local-version="localStatus.version"
          @open-deploy="openDeployModal"
        />

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
            <button class="btn btn-primary btn-sm" type="button" @click="activeTab = 'autonomy'">打开自治总览</button>
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

    <div v-show="activeTab === 'orders'" class="page-content admin-tab-panel">
      <XCmaxAdminOrdersTab />
    </div>
    <div v-show="activeTab === 'autonomy'" class="page-content admin-tab-panel">
      <XCmaxAdminAutonomyTab />
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
    <AdminDeployUpdateModal v-model="deployModalOpen" @done="handleDeployDone" />
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
import XCmaxAdminAutonomyTab from '@/components/admin/XCmaxAdminAutonomyTab.vue'
import XCmaxAdminOrdersTab from '@/components/admin/XCmaxAdminOrdersTab.vue'
import AdminReleaseStatusCard from '../components/admin/AdminReleaseStatusCard.vue'
import XcmaxDashboardEmbed from '@/components/admin/XcmaxDashboardEmbed.vue'
import AdminDeployUpdateModal from '@host/components/admin/AdminDeployUpdateModal.vue'
import {
  xcmaxAutomationPolicyEmbedUrl,
  xcmaxDutyTimeArchitectureEmbedUrl,
} from '@/constants/xcmaxDashboardEmbed'
import { useXcmaxOverview } from './xcmaxAdmin/useXcmaxOverview'
import { useXcmaxSync } from './xcmaxAdmin/useXcmaxSync'
import { useXcmaxAutonomyHealth } from './xcmaxAdmin/useXcmaxAutonomyHealth'

const adminTabs = [
  { id: 'overview', label: '总览' },
  { id: 'orders', label: '订单经营' },
  { id: 'autonomy', label: '自治总览' },
  { id: 'infra', label: '基础设施' },
  { id: 'duty', label: '编制与调度' },
  { id: 'automation-policy', label: '自动化方针' },
  { id: 'duty-time-architecture', label: '同时完成时间架构' },
]
const activeTab = ref('overview')
const automationEmbedUrl = xcmaxAutomationPolicyEmbedUrl()
const timeArchEmbedUrl = xcmaxDutyTimeArchitectureEmbedUrl()

const {
  syncingEmployees,
  localStatus,
  remoteStatus,
  modules,
  remoteEmployees,
  recentErrors,
  sourceLabel,
  loadLocalStatus,
  loadRemoteStatus,
  loadModules,
  loadRemoteEmployees,
  syncEmployees,
} = useXcmaxOverview()

const {
  syncing,
  syncStatus,
  conflicts,
  loadSyncStatus,
  triggerPush,
  triggerPull,
  loadConflicts,
  resolveConflict,
  startSyncStream,
  stopSyncStream,
} = useXcmaxSync({ recentErrors })

const {
  autonomyHealthLoading,
  autonomyHealth,
  loadAutonomyHealth,
} = useXcmaxAutonomyHealth()

const refreshing = ref(false)
const deployModalOpen = ref(false)
const releaseStatusCard = ref(null)
/** 首次进入时拉取；之后依赖缓存与「刷新状态」 */
const overviewBootstrapped = ref(false)

function openDeployModal() {
  deployModalOpen.value = true
}

async function handleDeployDone() {
  await releaseStatusCard.value?.refresh?.()
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
      releaseStatusCard.value?.refresh?.(),
      loadAutonomyHealth(),
    ])
    if (syncStatus.value.conflictCount > 0) await loadConflicts()
  } finally {
    refreshing.value = false
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

<style scoped src="./XCmaxAdminView.css"></style>
