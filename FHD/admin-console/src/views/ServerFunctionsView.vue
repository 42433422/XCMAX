<template>
  <div class="server-functions-view" id="view-server-functions">
    <div class="page-content admin-screen">
      <div class="page-header">
        <div>
          <h2>每日摘要</h2>
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

      <section class="digest-layout admin-pane">
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
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { sanitizeChatBubbleHtml } from '@/utils/sanitizeHtml'
import { useDigestPanel } from './serverFunctions/useDigestPanel'

/** 页面已收敛为每日摘要；保留 TabKey 形状供轮询逻辑判断。 */
const activeTab = ref('digests') as Ref<'modules' | 'digests'>
const refreshing = ref(false)

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

function sanitizeHtml(raw: string) {
  return sanitizeChatBubbleHtml(raw)
}

async function refreshActiveTab() {
  refreshing.value = true
  try {
    await loadDigestRecords()
  } finally {
    refreshing.value = false
  }
}

onMounted(() => {
  void loadDigestRecords()
  void fetchLatestIdentityCode()
  startDigestPolling()
})

onBeforeUnmount(() => {
  stopDigestPolling()
})
</script>

<style scoped src="./ServerFunctionsView.css"></style>
