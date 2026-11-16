<template>
  <div class="server-functions-view" id="view-server-functions">
    <div class="page-content admin-screen">
      <div class="page-header">
        <div>
          <h2>服务器功能模块</h2>
        </div>
        <div class="header-actions">
          <button type="button"
            v-if="latestIdentityCode"
            class="identity-badge"
            :title="identityBadgeTitle"
            @click="copyIdentityCode"
          >
            <i class="fa fa-shield" aria-hidden="true"></i>
            身份码 <code>{{ latestIdentityCode }}</code>
            <i v-if="identityCopied" class="fa fa-check" aria-hidden="true" style="color:#10b759"></i>
          </button>
          <button class="btn btn-secondary" :disabled="refreshing" @click="refreshActiveTab">
            <i class="fa fa-refresh" :class="{ 'fa-spin': refreshing }" aria-hidden="true"></i>
            {{ refreshing ? '刷新中...' : '刷新当前' }}
          </button>
          <details v-if="latestIdentityCode && digestApiBase" class="connection-details">
            <summary>连接信息</summary><code>{{ digestApiBase }}</code>
            <a v-if="marketWebFromDigest" :href="marketWebFromDigest" target="_blank" rel="noopener noreferrer">打开市场</a>
          </details>
        </div>
      </div>

      <nav class="tabs" aria-label="服务器功能模块">
        <button :class="{ active: activeTab === 'modules' }" :aria-pressed="activeTab === 'modules'" @click="activeTab = 'modules'">
          服务器模块
        </button>
        <button :class="{ active: activeTab === 'digests' }" :aria-pressed="activeTab === 'digests'" @click="activeTab = 'digests'">
          每日摘要记录
        </button>
      </nav>

      <section v-if="activeTab === 'modules'" class="modules-panel">
        <div class="module-metrics" aria-label="模块统计">
          <div><span>注册模块</span><strong>{{ modulesKnown ? modules.length : '—' }}</strong></div>
          <div><span>已启用</span><strong>{{ modulesKnown ? enabledModules : '—' }}</strong></div>
          <div><span>已禁用</span><strong>{{ modulesKnown ? modules.length - enabledModules : '—' }}</strong></div>
        </div>
        <section class="card module-list">
          <div class="module-toolbar">
            <h3>模块列表 <small>{{ filteredModules.length }} / {{ modules.length }}</small></h3>
            <div class="module-filters">
              <input v-model="moduleQuery" type="search" aria-label="搜索模块" placeholder="搜索名称或 ID" />
              <select v-model="moduleStatus" aria-label="模块状态"><option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已禁用</option></select>
            </div>
          </div>
          <p v-if="modulesLoading" class="empty-hint" role="status">正在读取模块…</p>
          <div v-else-if="modulesError" class="error-hint" role="alert">{{ modulesError }} <button class="btn btn-secondary" @click="loadModules">重试</button></div>
          <div v-else-if="filteredModules.length" class="table-scroll">
            <table class="data-table">
              <thead><tr><th>模块</th><th>来源</th><th>状态</th><th>详情</th></tr></thead>
              <tbody><tr v-for="mod in filteredModules" :key="mod.module_id">
                <td><strong class="module-name">{{ mod.display_name || mod.name || '未命名模块' }}</strong><small class="module-id mono">{{ mod.module_id }}</small></td>
                <td>{{ sourceLabel(mod.source) }}</td>
                <td><span class="status-badge" :class="mod.active === false ? 'badge-dim' : 'badge-ok'">{{ mod.active === false ? '禁用' : '启用' }}</span></td>
                <td><details class="module-detail"><summary>查看</summary><dl><dt>路由</dt><dd class="mono">{{ mod.route || '—' }}</dd><dt>同步范围</dt><dd>{{ mod.sync_scope || '—' }}</dd></dl></details></td>
              </tr></tbody>
            </table>
          </div>
          <p v-else class="empty-hint">{{ modules.length ? '没有匹配的模块' : '暂无模块数据' }}</p>
        </section>
      </section>

      <section v-if="activeTab === 'digests'" class="digest-layout admin-pane">
        <div class="card digest-list-card">
          <div class="section-title">
            <h3>每日摘要存档</h3>
            <button class="btn btn-secondary btn-sm" :disabled="digestLoading" @click="loadDigestRecords">
              {{ digestLoading ? '读取中...' : '刷新摘要' }}
            </button>
          </div>
          <p v-if="digestLastSynced" class="sync-time">上次同步 {{ digestLastSynced }}</p>
          <p v-if="digestError" class="error-hint">{{ digestError }}</p>
          <div v-if="digestRecords.length" class="digest-list">
            <button
              v-for="row in digestRecords"
              :key="row.id"
              type="button"
              class="digest-item"
              :class="{ active: selectedDigestId === row.id }"
              @click="selectDigest(row.id)"
            >
              <span class="digest-subject">{{ row.subject || `每日摘要 #${row.id}` }}</span>
              <span class="digest-meta">
                {{ row.day || '—' }} · {{ row.delivered ? '已投递' : '未投递' }} · {{ row.created_at || '—' }}
              </span>
              <span class="digest-excerpt">{{ row.body_text || '无纯文本摘要' }}</span>
            </button>
          </div>
          <p v-else-if="!digestLoading" class="empty-hint">暂无每日摘要记录。</p>
        </div>

        <div class="card digest-detail-card">
          <div class="section-title">
            <h3>摘要全文</h3>
            <span v-if="digestDetail" class="pill">{{ digestDetail.delivered ? '已投递' : '未投递' }}</span>
          </div>
          <p v-if="digestDetailLoading" class="empty-hint">正在读取完整摘要...</p>
          <template v-else-if="digestDetail">
            <div class="digest-detail-meta">
              <span>主题：{{ digestDetail.subject }}</span>
              <span>日期：{{ digestDetail.day || '—' }}</span>
              <span>收件人：{{ (digestDetail.recipients || []).join('、') || '—' }}</span>
            </div>
            <div class="digest-html" v-html="sanitizeHtml(digestDetail.body_html || digestDetail.body_text || '')"></div>
            <details class="raw-block">
              <summary>查看投递结果 JSON</summary>
              <pre>{{ formatJson(digestDetail.delivery || []) }}</pre>
            </details>
          </template>
          <p v-else class="empty-hint">请选择左侧摘要记录。</p>
        </div>
      </section>


    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api'
import { sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import { useDigestPanel } from './serverFunctions/useDigestPanel'

type AnyRow = Record<string, any>

const activeTab = ref<'modules' | 'digests'>('modules')
const refreshing = ref(false)

const modules = ref<AnyRow[]>([])
const modulesLoading = ref(false), modulesKnown = ref(false), modulesError = ref('')
const moduleQuery = ref(''), moduleStatus = ref('all')
const enabledModules = computed(() => modules.value.filter(mod => mod.active !== false).length)
const filteredModules = computed(() => modules.value.filter(mod => {
  const matches = `${mod.display_name || mod.name || ''} ${mod.module_id || ''}`.toLowerCase().includes(moduleQuery.value.trim().toLowerCase())
  return matches && (moduleStatus.value === 'all' || (moduleStatus.value === 'enabled' ? mod.active !== false : mod.active === false))
}))

const {
  digestRecords,
  digestDetail,
  selectedDigestId,
  digestLoading,
  digestDetailLoading,
  digestError,
  digestLastSynced,
  digestApiBase,
  latestIdentityCode,
  identityCopied,
  marketWebFromDigest,
  identityBadgeTitle,
  copyIdentityCode,
  loadDigestRecords,
  selectDigest,
  stopDigestPolling,
  startDigestPolling,
  fetchLatestIdentityCode,
} = useDigestPanel(activeTab)

function sourceLabel(source: string) {
  const map: Record<string, string> = { local: '本地 Mod', remote: '服务器', core: '系统内置', employee: '员工包' }
  return map[source] || source || '未知'
}

function sanitizeHtml(raw: string) {
  return sanitizeChatBubbleHtml(raw)
}

async function loadModules() {
  if (modulesLoading.value) return
  modulesLoading.value = true
  modulesError.value = ''
  try {
    const res = await api.get<any>('/api/xcmax/admin/modules')
    if (res?.success === false || !Array.isArray(res?.data)) throw new Error('模块数据返回不完整')
    modules.value = res.data
    modulesKnown.value = true
  } catch (e) {
    modules.value = []
    modulesKnown.value = false
    modulesError.value = e instanceof Error ? e.message : '模块读取失败'
  } finally { modulesLoading.value = false }
}

async function refreshActiveTab() {
  refreshing.value = true
  try {
    if (activeTab.value === 'modules') await loadModules()
    else if (activeTab.value === 'digests') await loadDigestRecords()
  } finally {
    refreshing.value = false
  }
}

watch(activeTab, (tab) => {
  if (tab === 'modules' && modules.value.length === 0) void loadModules()
  if (tab === 'digests') {
    void loadDigestRecords()
    startDigestPolling()
  } else {
    stopDigestPolling()
  }
})

onMounted(() => {
  void loadModules()
  void fetchLatestIdentityCode()
})

onBeforeUnmount(() => {
  stopDigestPolling()
})
</script>

<style scoped src="./ServerFunctionsView.css"></style>
