<template>
  <div class="server-functions-view" id="view-server-functions">
    <div class="page-content">
      <div class="page-header">
        <div>
          <h2>服务器功能模块</h2>
          <p>对接修茈服务器的模块注册、每日摘要记录和员工大会能力。</p>
        </div>
        <div class="header-actions">
          <span
            v-if="latestIdentityCode"
            class="identity-badge"
            :title="identityBadgeTitle"
            @click="copyIdentityCode"
          >
            <i class="fa fa-shield" aria-hidden="true"></i>
            身份码 <code>{{ latestIdentityCode }}</code>
            <i v-if="identityCopied" class="fa fa-check" aria-hidden="true" style="color:#10b759"></i>
          </span>
          <button class="btn btn-secondary" :disabled="refreshing" @click="refreshActiveTab">
            <i class="fa fa-refresh" :class="{ 'fa-spin': refreshing }" aria-hidden="true"></i>
            {{ refreshing ? '刷新中...' : '刷新当前' }}
          </button>
          <p v-if="latestIdentityCode && digestApiBase" class="identity-hint">
            管理端解锁须在本身份码的<strong>同一 MODstore API</strong>对应的修茈市场提交（当前 API：<code>{{ digestApiBase }}</code>）。
            <a v-if="marketWebFromDigest" class="identity-hint__link" :href="marketWebFromDigest" target="_blank" rel="noopener noreferrer">打开市场</a>
          </p>
        </div>
      </div>

      <div class="tabs" role="tablist" aria-label="服务器功能模块">
        <button :class="{ active: activeTab === 'modules' }" @click="activeTab = 'modules'; loadModules()">
          服务器模块
        </button>
        <button :class="{ active: activeTab === 'digests' }" @click="activeTab = 'digests'; loadDigestRecords()">
          每日摘要记录
        </button>
        <button :class="{ active: activeTab === 'allHands' }" @click="activeTab = 'allHands'">
          员工大会
        </button>
      </div>

      <section v-if="activeTab === 'modules'" class="card">
        <div class="section-title">
          <h3>服务器功能注册表</h3>
          <span class="pill">{{ modules.length }} 个模块</span>
        </div>
        <table class="data-table" v-if="modules.length">
          <thead>
            <tr>
              <th>模块 ID</th>
              <th>名称</th>
              <th>来源</th>
              <th>状态</th>
              <th>路由</th>
              <th>同步范围</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="mod in modules" :key="mod.module_id">
              <td class="mono">{{ mod.module_id }}</td>
              <td>{{ mod.display_name || mod.name || '-' }}</td>
              <td>{{ sourceLabel(mod.source) }}</td>
              <td>
                <span class="status-badge" :class="mod.active === false ? 'badge-dim' : 'badge-ok'">
                  {{ mod.active === false ? '禁用' : '启用' }}
                </span>
              </td>
              <td class="mono small">{{ mod.route || '—' }}</td>
              <td class="small">{{ mod.sync_scope || '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-hint">暂无模块数据，点击刷新或检查 /api/xcmax/admin/modules。</p>
      </section>

      <section v-if="activeTab === 'digests'" class="digest-layout">
        <div class="card digest-list-card">
          <div class="section-title">
            <h3>每日摘要存档</h3>
            <button class="btn btn-secondary btn-sm" :disabled="digestLoading" @click="loadDigestRecords">
              {{ digestLoading ? '读取中...' : '刷新摘要' }}
            </button>
          </div>
          <p class="section-note">
            服务器每日摘要仍会照常发邮箱，这里读取服务器落库的同一份完整副本，便于后台随时回看。
            <span v-if="digestLastSynced" class="sync-time">上次同步 {{ digestLastSynced }}</span>
          </p>
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
          <p v-else-if="!digestLoading" class="empty-hint">暂无每日摘要记录。下一次服务器发送摘要后会自动存档。</p>
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

      <section v-if="activeTab === 'allHands'" class="card allhands-card">
        <div class="section-title">
          <h3>服务器员工大会</h3>
          <span v-if="allHandsSessionId" class="pill">会话 {{ allHandsSessionId.slice(0, 8) }}</span>
        </div>
        <p class="section-note">
          直接调用服务器员工大会：可生成全员架构汇报，也可向所有在岗员工提问并让数字管家综合答复。下方保留完整员工原文、会议摘要和原始 JSON。
        </p>

        <div class="allhands-controls">
          <label>
            <span>向员工大会提问（可选）</span>
            <textarea
              v-model="allHandsQuestion"
              rows="3"
              maxlength="600"
              placeholder="例如：有没有员工负责每日摘要存档？当前服务器有哪些高风险问题？"
              :disabled="allHandsBusy"
            ></textarea>
          </label>
          <label>
            <span>最多员工</span>
            <input v-model.number="allHandsMaxEmployees" type="number" min="1" max="20" :disabled="allHandsBusy">
          </label>
          <label>
            <span>并发</span>
            <select v-model.number="allHandsConcurrency" :disabled="allHandsBusy">
              <option :value="1">1</option>
              <option :value="2">2</option>
              <option :value="3">3</option>
              <option :value="4">4</option>
            </select>
          </label>
          <label class="check-row">
            <input v-model="allHandsWithResearch" type="checkbox" :disabled="allHandsBusy || Boolean(allHandsQuestion.trim())">
            <span>联网 + GitHub 调研</span>
          </label>
        </div>

        <div class="card-actions">
          <button class="btn btn-primary" :disabled="allHandsBusy" @click="startAllHands(false)">
            {{ allHandsBusy ? '员工大会进行中...' : '生成全员架构汇报' }}
          </button>
          <button class="btn btn-secondary" :disabled="allHandsBusy || !allHandsQuestion.trim()" @click="startAllHands(true)">
            向员工大会提问
          </button>
          <button v-if="allHandsReport" class="btn btn-secondary" @click="downloadAllHandsJson">导出完整 JSON</button>
        </div>

        <p v-if="allHandsError" class="error-hint">{{ allHandsError }}</p>
        <div v-if="allHandsBusy" class="progress-box">
          <div class="progress-head">
            <span>
              {{ allHandsStageLabel }} · {{ allHandsProgress.completed }}/{{ allHandsProgress.total || allHandsMaxEmployees }}
            </span>
            <span>{{ allHandsProgress.percent }}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${allHandsProgress.percent}%` }"></div>
          </div>
          <p>
            成功 {{ allHandsProgress.ok }} · 异常 {{ allHandsProgress.error }}
            <span v-if="allHandsProgress.current_employee_name">
              · 最近完成 {{ allHandsProgress.current_employee_name }}
            </span>
          </p>
          <p v-if="allHandsStallHint" class="stall-hint">{{ allHandsStallHint }}</p>
        </div>

        <div v-if="allHandsReport" class="allhands-result">
          <div class="summary-pills">
            <span class="pill">共 {{ allHandsReport.summary?.total ?? allHandsReport.employees?.length ?? 0 }} 人</span>
            <span class="pill ok">完成 {{ allHandsReport.summary?.ok ?? 0 }}</span>
            <span class="pill warn">异常 {{ allHandsReport.summary?.error ?? 0 }}</span>
            <span class="pill">模型 {{ allHandsReport.summary?.bench_provider || '—' }}/{{ allHandsReport.summary?.bench_model || '—' }}</span>
          </div>

          <section v-if="allHandsReport.synthesized_answer?.markdown" class="result-section">
            <h4>数字管家综合答复</h4>
            <p class="section-note">问题：{{ allHandsReport.synthesized_answer.question }}</p>
            <div class="markdown-body" v-html="renderMarkdown(allHandsReport.synthesized_answer.markdown)"></div>
          </section>

          <section v-if="allHandsMeetingMinutes?.text" class="result-section">
            <h4>会议摘要</h4>
            <div class="markdown-body" v-html="renderMarkdown(allHandsMeetingMinutes.text)"></div>
            <details class="raw-block" v-if="allHandsMeetingMinutesEmail">
              <summary>会议摘要邮件投递结果</summary>
              <pre>{{ formatJson(allHandsMeetingMinutesEmail) }}</pre>
            </details>
          </section>

          <section class="result-section">
            <h4>员工完整汇报</h4>
            <article v-for="row in allHandsReport.employees || []" :key="row.employee_id" class="employee-report">
              <header class="employee-report__head">
                <div class="employee-report__title-row">
                  <h3 class="employee-report__title">{{ row.name || row.employee_id }}</h3>
                  <span
                    class="status-badge employee-report__status"
                    :class="row.status === 'ok' ? 'badge-ok' : 'badge-warn'"
                  >
                    {{ row.status === 'ok' ? '正常' : row.status || '—' }}
                  </span>
                </div>
                <p class="employee-report__id-line">
                  <code class="employee-report__id">{{ row.employee_id }}</code>
                </p>
              </header>
              <div
                class="markdown-body employee-report__markdown"
                v-html="renderMarkdown(row.report_markdown || '（无汇报正文）')"
              ></div>
              <details class="raw-block">
                <summary>查看该员工原始数据</summary>
                <pre>{{ formatJson(row) }}</pre>
              </details>
            </article>
          </section>
        </div>
      </section>

      
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api'
import { sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown } from '@/utils/sanitizeHtml'
import { useAllHands } from './serverFunctions/useAllHands'
import { useDigestPanel } from './serverFunctions/useDigestPanel'

type AnyRow = Record<string, any>

const activeTab = ref<'modules' | 'digests' | 'allHands'>('modules')
const refreshing = ref(false)

const modules = ref<AnyRow[]>([])

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

function formatJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value ?? '')
  }
}

const {
  allHandsQuestion,
  allHandsMaxEmployees,
  allHandsConcurrency,
  allHandsWithResearch,
  allHandsBusy,
  allHandsError,
  allHandsSessionId,
  allHandsReport,
  allHandsMeetingMinutes,
  allHandsMeetingMinutesEmail,
  allHandsProgress,
  allHandsStallHint,
  allHandsStageLabel,
  startAllHands,
  downloadAllHandsJson,
  stopAllHandsPolling,
} = useAllHands(formatJson)

function sourceLabel(source: string) {
  const map: Record<string, string> = { local: '本地 Mod', remote: '服务器', core: '系统内置', employee: '员工包' }
  return map[source] || source || '未知'
}

function sanitizeHtml(raw: string) {
  return sanitizeChatBubbleHtml(raw)
}

function renderMarkdown(raw: string) {
  return sanitizeChatBubbleMarkdown(raw)
}

async function loadModules() {
  try {
    const res = await api.get<any>('/api/xcmax/admin/modules')
    modules.value = Array.isArray(res?.data) ? res.data : []
  } catch (e) {
    modules.value = []
  }
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
  stopAllHandsPolling()
  stopDigestPolling()
})
</script>

<style scoped src="./ServerFunctionsView.css"></style>
