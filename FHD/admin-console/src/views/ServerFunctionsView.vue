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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '@/api'
import { sanitizeChatBubbleHtml, sanitizeChatBubbleMarkdown } from '@/utils/sanitizeHtml'

type AnyRow = Record<string, any>

const activeTab = ref<'modules' | 'digests' | 'allHands'>('modules')
const refreshing = ref(false)

const modules = ref<AnyRow[]>([])

const digestRecords = ref<AnyRow[]>([])
const digestDetail = ref<AnyRow | null>(null)
const selectedDigestId = ref<number | null>(null)
const digestLoading = ref(false)
const digestDetailLoading = ref(false)
const digestError = ref('')
const digestLastSynced = ref('')
const DIGEST_POLL_INTERVAL_MS = 5 * 60 * 1000
let digestPollTimer = 0
const CACHE_KEY = 'xcmax_digest_identity_code'
const CACHE_TTL_MS = 36 * 60 * 60 * 1000

/** FHD 在 digest-identity 的 data 中注入，与 XCAGI_MARKET_BASE_URL 一致 */
const digestApiBase = ref('')

function readCachedIdentityCode(): string {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return ''
    const obj = JSON.parse(raw)
    if (!obj?.code || !obj?.ts) return ''
    if (Date.now() - obj.ts > CACHE_TTL_MS) {
      localStorage.removeItem(CACHE_KEY)
      return ''
    }
    return obj.code
  } catch {
    return ''
  }
}

function writeCachedIdentityCode(code: string) {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ code, ts: Date.now() }))
  } catch { /* quota exceeded etc. */ }
}

/** 服务端无有效身份码时清掉本地缓存，避免页眉仍显示过期码、与解锁/空摘要列表不一致。 */
function clearDigestIdentityCache() {
  try {
    localStorage.removeItem(CACHE_KEY)
  } catch {
    /* ignore */
  }
  latestIdentityCode.value = ''
  digestApiBase.value = ''
}

const latestIdentityCode = ref(readCachedIdentityCode())
const identityCopied = ref(false)
let identityCopiedTimer = 0

const marketWebFromDigest = computed(() => {
  const b = digestApiBase.value.trim().replace(/\/$/, '')
  if (!/^https?:\/\//i.test(b)) return ''
  return `${b}/market`
})

const identityBadgeTitle = computed(() => {
  const base = digestApiBase.value.trim()
  const tail = base
    ? ` 当前签发 API：${base}。解锁须在该 API 对应的修茈市场（通常 ${base}/market）提交本码，与 POST /api/auth/verify-admin-digest-code 同源。`
    : ''
  return `修茈市场管理端解锁用；由服务器 /api/xcmax/admin/digest-identity 与解锁校验同源。选中历史摘要不改变此码。点击复制。${tail}`
})

const allHandsQuestion = ref('')
const allHandsMaxEmployees = ref(20)
const allHandsConcurrency = ref(2)
const allHandsWithResearch = ref(true)
const allHandsBusy = ref(false)
const allHandsError = ref('')
const allHandsSessionId = ref('')
const allHandsReport = ref<AnyRow | null>(null)
const allHandsMeetingMinutes = ref<AnyRow | null>(null)
const allHandsMeetingMinutesEmail = ref<AnyRow | null>(null)
const allHandsProgress = ref({
  stage: 'prepare',
  total: 0,
  completed: 0,
  ok: 0,
  error: 0,
  percent: 0,
  current_employee_id: '',
  current_employee_name: '',
  current_employee_status: '',
  updated_at: '',
})

let allHandsPollTimer = 0
const allHandsStallHint = ref('')
let allHandsStallSince = 0
let allHandsStallSnapshot = ''

const ALL_HANDS_STAGE_LABELS: Record<string, string> = {
  prepare: '准备员工清单',
  collect: '收集员工汇报',
  employee_done: '收集员工汇报',
  completed: '汇报汇总',
  synthesize: '数字管家综合答复',
  minutes: '生成会议摘要',
}

const allHandsStageLabel = computed(() => {
  const stage = String(allHandsProgress.value.stage || 'collect').toLowerCase()
  return ALL_HANDS_STAGE_LABELS[stage] || '员工大会进行中'
})

const selectedDigest = computed(() =>
  digestRecords.value.find((row) => Number(row.id) === Number(selectedDigestId.value)) || null,
)

function extractDigestIdentityCode(html: string): string {
  const m = html.match(/身份校验码[\s\S]*?<code[^>]*>([0-9A-Fa-f]{6})<\/code>/i)
  return m ? String(m[1]).toUpperCase() : ''
}

/** 与 MODstore ``digest_identity`` 模块一致：优先走同源接口，旧服务器再解析 HTML。 */
async function syncDigestIdentityBadge(fallbackHtml?: string) {
  let digestIdentityApiOk = false
  try {
    const res = await api.get<any>('/api/xcmax/admin/digest-identity')
    digestIdentityApiOk = true
    const d = res?.data && typeof res.data === 'object' ? res.data : null
    if (d && (d as Record<string, unknown>).digest_api_base != null) {
      digestApiBase.value = String((d as Record<string, unknown>).digest_api_base).trim()
    }
    const c = d?.code ? String(d.code).trim().toUpperCase() : ''
    if (c.length === 6 && /^[0-9A-F]{6}$/.test(c)) {
      latestIdentityCode.value = c
      writeCachedIdentityCode(c)
      return
    }
  } catch {
    /* 远端未提供 digest-identity 时由 HTML 后备 */
  }
  if (fallbackHtml) {
    const code = extractDigestIdentityCode(fallbackHtml)
    if (code) {
      digestApiBase.value = ''
      latestIdentityCode.value = code
      writeCachedIdentityCode(code)
      return
    }
  }
  // 接口已成功但无有效码：清掉旧缓存（否则页眉长期显示与「暂无摘要」矛盾的过期身份码）
  if (digestIdentityApiOk) {
    clearDigestIdentityCache()
  }
}

function copyIdentityCode() {
  const code = latestIdentityCode.value
  if (!code) return
  const done = () => {
    identityCopied.value = true
    window.clearTimeout(identityCopiedTimer)
    identityCopiedTimer = window.setTimeout(() => {
      identityCopied.value = false
    }, 1500)
  }
  const w = navigator.clipboard?.writeText
  if (typeof w === 'function') {
    void w.call(navigator.clipboard, code).then(done).catch(fallbackCopyPlainText)
    return
  }
  fallbackCopyPlainText()

  function fallbackCopyPlainText() {
    try {
      const ta = document.createElement('textarea')
      ta.value = code
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.left = '-9999px'
      ta.style.top = '0'
      document.body.appendChild(ta)
      ta.focus()
      ta.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(ta)
      if (ok) done()
    } catch {
      /* 非 HTTPS / 无剪贴板权限时静默失败 */
    }
  }
}

function sourceLabel(source: string) {
  const map: Record<string, string> = { local: '本地 Mod', remote: '服务器', core: '系统内置', employee: '员工包' }
  return map[source] || source || '未知'
}

function formatJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value ?? '')
  }
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

async function loadDigestRecords() {
  digestLoading.value = true
  digestError.value = ''
  try {
    const res = await api.get<any>('/api/xcmax/admin/daily-digests', { limit: 30 })
    const rows = Array.isArray(res?.data) ? res.data : []
    digestRecords.value = rows
    digestLastSynced.value = new Date().toLocaleTimeString()
    await syncDigestIdentityBadge()
    if (rows.length) {
      const latestId = Number(rows[0].id)
      if (!latestIdentityCode.value) {
        try {
          const detailRes = await api.get<any>(`/api/xcmax/admin/daily-digests/${latestId}`)
          const html = detailRes?.data?.body_html || ''
          await syncDigestIdentityBadge(String(html))
        } catch { /* best-effort */ }
      }
      if (!selectedDigestId.value || !rows.some((r: any) => Number(r.id) === Number(selectedDigestId.value))) {
        await selectDigest(latestId)
      }
    }
  } catch (e) {
    digestError.value = e instanceof Error ? e.message : String(e)
  } finally {
    digestLoading.value = false
  }
}

async function selectDigest(id: number) {
  selectedDigestId.value = id
  digestDetailLoading.value = true
  digestError.value = ''
  try {
    const res = await api.get<any>(`/api/xcmax/admin/daily-digests/${id}`)
    digestDetail.value = res?.data && typeof res.data === 'object' ? res.data : selectedDigest.value
  } catch (e) {
    digestError.value = e instanceof Error ? e.message : String(e)
  } finally {
    digestDetailLoading.value = false
  }
}

function resetAllHandsProgress(total: number) {
  allHandsProgress.value = {
    stage: 'prepare',
    total,
    completed: 0,
    ok: 0,
    error: 0,
    percent: 0,
    current_employee_id: '',
    current_employee_name: '',
    current_employee_status: '',
    updated_at: '',
  }
}

function touchAllHandsStallWatch() {
  const snap = [
    allHandsProgress.value.stage,
    allHandsProgress.value.completed,
    allHandsProgress.value.total,
    allHandsProgress.value.current_employee_id,
  ].join('|')
  if (snap !== allHandsStallSnapshot) {
    allHandsStallSnapshot = snap
    allHandsStallSince = Date.now()
    allHandsStallHint.value = ''
    return
  }
  if (!allHandsBusy.value) return
  const stalledMs = Date.now() - allHandsStallSince
  if (stalledMs < 120_000) return
  const stage = String(allHandsProgress.value.stage || '').toLowerCase()
  if (stage === 'minutes' || stage === 'synthesize') {
    allHandsStallHint.value = '会议摘要/综合答复生成较慢，请继续等待…'
    return
  }
  const name = allHandsProgress.value.current_employee_name || allHandsProgress.value.current_employee_id
  allHandsStallHint.value = name
    ? `「${name}」汇报超过 2 分钟无进展，可能 LLM 较慢；单员工默认 300s 超时后会自动跳过`
    : '进度超过 2 分钟无变化，请检查 MODstore :8788 日志或稍后重试'
}

function applyAllHandsProgress(raw: AnyRow | null | undefined) {
  if (!raw || typeof raw !== 'object') return
  const prev = allHandsProgress.value
  const total = Math.max(0, Number(raw.total ?? prev.total) || 0)
  const completed = Math.max(0, Math.min(Number(raw.completed ?? prev.completed) || 0, total || Number.MAX_SAFE_INTEGER))
  const percentRaw = Number(raw.percent)
  allHandsProgress.value = {
    stage: String(raw.stage ?? prev.stage ?? 'collect'),
    total,
    completed,
    ok: Math.max(0, Number(raw.ok ?? prev.ok) || 0),
    error: Math.max(0, Number(raw.error ?? prev.error) || 0),
    percent: Number.isFinite(percentRaw)
      ? Math.max(0, Math.min(100, Math.round(percentRaw)))
      : total > 0 ? Math.round((completed / total) * 100) : 0,
    current_employee_id: String(raw.current_employee_id ?? prev.current_employee_id ?? ''),
    current_employee_name: String(raw.current_employee_name ?? prev.current_employee_name ?? ''),
    current_employee_status: String(raw.current_employee_status ?? prev.current_employee_status ?? ''),
    updated_at: String(raw.updated_at ?? prev.updated_at ?? ''),
  }
  touchAllHandsStallWatch()
}

function stopAllHandsPolling() {
  if (allHandsPollTimer) {
    window.clearTimeout(allHandsPollTimer)
    allHandsPollTimer = 0
  }
}

async function pollAllHandsSession(sessionId: string) {
  stopAllHandsPolling()
  try {
    const sess = await api.get<any>(`/api/xcmax/admin/all-hands-report/sessions/${sessionId}`)
    applyAllHandsProgress(sess?.planning_record?.progress)
    if (sess?.status === 'done') {
      allHandsBusy.value = false
      const artifact = sess.artifact && typeof sess.artifact === 'object' ? sess.artifact : {}
      const report = artifact.all_hands_report
      if (!report || typeof report !== 'object') {
        allHandsError.value = '员工大会完成，但服务器没有返回有效报告内容'
        return
      }
      allHandsReport.value = report
      allHandsMeetingMinutes.value = artifact.meeting_minutes && typeof artifact.meeting_minutes === 'object'
        ? artifact.meeting_minutes
        : null
      allHandsMeetingMinutesEmail.value = artifact.meeting_minutes_email && typeof artifact.meeting_minutes_email === 'object'
        ? artifact.meeting_minutes_email
        : null
      applyAllHandsProgress({
        stage: 'completed',
        total: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
        completed: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
        ok: Number(report.summary?.ok ?? 0) || 0,
        error: Number(report.summary?.error ?? 0) || 0,
        percent: 100,
      })
      return
    }
    if (sess?.status === 'error') {
      allHandsBusy.value = false
      allHandsError.value = String(sess.error || '员工大会失败')
      return
    }
  } catch (e) {
    allHandsBusy.value = false
    allHandsError.value = e instanceof Error ? e.message : String(e)
    return
  }
  if (!allHandsBusy.value || allHandsSessionId.value !== sessionId) return
  allHandsPollTimer = window.setTimeout(() => {
    void pollAllHandsSession(sessionId)
  }, 2000)
}

async function startAllHands(withQuestion: boolean) {
  if (allHandsBusy.value) return
  stopAllHandsPolling()
  allHandsBusy.value = true
  allHandsError.value = ''
  allHandsSessionId.value = ''
  allHandsReport.value = null
  allHandsMeetingMinutes.value = null
  allHandsMeetingMinutesEmail.value = null
  allHandsStallHint.value = ''
  allHandsStallSince = Date.now()
  allHandsStallSnapshot = ''
  const maxEmployees = Math.max(1, Math.min(Number(allHandsMaxEmployees.value) || 20, 20))
  resetAllHandsProgress(maxEmployees)
  try {
    const question = allHandsQuestion.value.trim()
    const payload: AnyRow = {
      max_employees: maxEmployees,
      concurrency: Math.max(1, Math.min(Number(allHandsConcurrency.value) || 2, 4)),
      with_research: withQuestion && question ? false : allHandsWithResearch.value,
    }
    if (withQuestion && question) {
      payload.user_question = question
      payload.synthesize = true
    }
    const started = await api.post<any>('/api/xcmax/admin/all-hands-report/sessions', payload)
    const sid = String(started?.session_id || '').trim()
    if (!sid) throw new Error('服务器没有返回员工大会 session_id')
    allHandsSessionId.value = sid
    void pollAllHandsSession(sid)
  } catch (e) {
    allHandsBusy.value = false
    allHandsError.value = e instanceof Error ? e.message : String(e)
  }
}

function downloadAllHandsJson() {
  const data = {
    report: allHandsReport.value,
    meeting_minutes: allHandsMeetingMinutes.value,
    meeting_minutes_email: allHandsMeetingMinutesEmail.value,
  }
  const blob = new Blob([formatJson(data)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `server-all-hands-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
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

function stopDigestPolling() {
  if (digestPollTimer) {
    window.clearTimeout(digestPollTimer)
    digestPollTimer = 0
  }
}

function startDigestPolling() {
  stopDigestPolling()
  digestPollTimer = window.setTimeout(() => {
    if (activeTab.value === 'digests') {
      void loadDigestRecords().then(() => startDigestPolling())
    } else {
      startDigestPolling()
    }
  }, DIGEST_POLL_INTERVAL_MS)
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

async function fetchLatestIdentityCode() {
  try {
    await syncDigestIdentityBadge()
  } catch { /* best-effort */ }
}

onMounted(() => {
  void loadModules()
  void fetchLatestIdentityCode()
})

onBeforeUnmount(() => {
  stopAllHandsPolling()
  stopDigestPolling()
})
</script>

<style scoped>
.server-functions-view {
  min-height: 100vh;
  background: linear-gradient(135deg, #edf5fb 0%, #e7eef6 100%);
}

.page-content {
  padding: 24px 28px;
  max-width: 1400px;
  margin: 0 auto;
}

.page-header,
.section-title,
.card-actions,
.summary-pills {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.page-header h2,
.section-title h3,
.result-section h4 {
  margin: 0;
  color: #172033;
}

.page-header p,
.section-note {
  margin: 6px 0 0;
  color: rgba(23, 32, 51, 0.58);
  font-size: 13px;
}

.sync-time {
  margin-left: 12px;
  color: rgba(23, 32, 51, 0.38);
  font-size: 12px;
}

.tabs {
  display: flex;
  gap: 8px;
  margin: 18px 0;
}

.tabs button {
  border: 1px solid rgba(24, 144, 255, 0.18);
  background: rgba(255, 255, 255, 0.72);
  color: #172033;
  padding: 10px 22px;
  border-radius: 10px;
  cursor: pointer;
  font-weight: 700;
}

.tabs button.active {
  background: #1890ff;
  color: #fff;
  border-color: #1890ff;
}

.card {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(15, 76, 129, 0.1);
  border-radius: 18px;
  box-shadow: 0 8px 28px rgba(15, 76, 129, 0.08);
  padding: 22px;
}

.digest-layout {
  display: grid;
  grid-template-columns: minmax(300px, 380px) 1fr;
  gap: 18px;
  height: calc(100vh - 200px);
  min-height: 400px;
}

.digest-list-card {
  overflow-y: auto;
}

.digest-detail-card {
  overflow-y: auto;
}

.digest-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 16px;
}

.digest-item {
  text-align: left;
  border: 1px solid rgba(15, 76, 129, 0.1);
  border-radius: 12px;
  background: #fff;
  padding: 12px;
  cursor: pointer;
}

.digest-item.active {
  border-color: #1890ff;
  box-shadow: 0 0 0 3px rgba(24, 144, 255, 0.12);
}

.digest-subject,
.digest-meta,
.digest-excerpt {
  display: block;
}

.digest-subject {
  font-weight: 800;
  color: #172033;
}

.digest-meta,
.digest-excerpt {
  margin-top: 5px;
  font-size: 12px;
  color: rgba(23, 32, 51, 0.55);
}

.digest-excerpt {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.digest-detail-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 12px 0;
  color: rgba(23, 32, 51, 0.68);
  font-size: 13px;
}

.digest-html,
.markdown-body {
  background: #fff;
  border: 1px solid rgba(15, 76, 129, 0.08);
  border-radius: 12px;
  padding: 16px;
  overflow: auto;
}

.allhands-card {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.allhands-controls {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) 120px 120px 180px;
  gap: 12px;
  align-items: end;
}

.allhands-controls label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  font-weight: 700;
  color: rgba(23, 32, 51, 0.68);
}

.allhands-controls textarea,
.allhands-controls input,
.allhands-controls select {
  width: 100%;
  border: 1px solid rgba(15, 76, 129, 0.16);
  border-radius: 10px;
  padding: 9px 10px;
  background: #fff;
  color: #172033;
}

.check-row {
  flex-direction: row !important;
  align-items: center;
  padding-bottom: 8px;
}

.check-row input {
  width: auto;
}

.progress-box {
  padding: 14px;
  border-radius: 14px;
  background: rgba(24, 144, 255, 0.08);
  border: 1px solid rgba(24, 144, 255, 0.15);
}

.progress-head {
  display: flex;
  justify-content: space-between;
  font-weight: 800;
}

.progress-track {
  height: 8px;
  border-radius: 99px;
  background: rgba(24, 144, 255, 0.16);
  overflow: hidden;
  margin: 10px 0;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #1890ff, #35c7ff);
}

.stall-hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: #b45309;
  line-height: 1.5;
}

.allhands-result,
.result-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-section {
  margin-top: 12px;
}

.employee-report {
  border: 1px solid rgba(15, 76, 129, 0.12);
  border-radius: 16px;
  padding: 0;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.95) 0%, rgba(248, 250, 252, 0.92) 100%);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04), 0 8px 24px rgba(15, 76, 129, 0.06);
  overflow: hidden;
}

.employee-report__head {
  padding: 16px 18px 14px;
  border-bottom: 1px solid rgba(15, 76, 129, 0.1);
  background: rgba(255, 255, 255, 0.55);
}

.employee-report__title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.employee-report__title {
  margin: 0;
  font-size: 1.125rem;
  font-weight: 700;
  line-height: 1.35;
  color: #0f172a;
  letter-spacing: -0.02em;
  flex: 1;
  min-width: 0;
}

.employee-report__status {
  flex-shrink: 0;
  margin-top: 2px;
  text-transform: none;
}

.employee-report__id-line {
  margin: 10px 0 0;
}

.employee-report__id {
  display: inline-block;
  font-family: ui-monospace, Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 8px;
  background: rgba(15, 76, 129, 0.06);
  color: #475569;
  border: 1px solid rgba(15, 76, 129, 0.12);
  letter-spacing: 0.01em;
}

.employee-report__markdown {
  margin: 0;
  border: none;
  border-radius: 0;
  padding: 18px 18px 16px;
  background: #fafbfd;
}

.employee-report__markdown :deep(h1) {
  font-size: 1.2rem;
  font-weight: 700;
  line-height: 1.35;
  margin: 0 0 12px;
  color: #0f172a;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(15, 76, 129, 0.1);
}

.employee-report__markdown :deep(h2),
.employee-report__markdown :deep(h3) {
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.4;
  margin: 1.15rem 0 0.5rem;
  color: #1e293b;
}

.employee-report__markdown :deep(h2:first-child),
.employee-report__markdown :deep(h3:first-child) {
  margin-top: 0;
}

.employee-report__markdown :deep(p) {
  margin: 0.55rem 0;
  line-height: 1.65;
  color: rgba(23, 32, 51, 0.88);
  font-size: 14px;
}

.employee-report__markdown :deep(ul),
.employee-report__markdown :deep(ol) {
  margin: 0.5rem 0 0.65rem;
  padding-left: 1.35rem;
  line-height: 1.6;
  font-size: 14px;
  color: rgba(23, 32, 51, 0.88);
}

.employee-report__markdown :deep(li) {
  margin: 0.25rem 0;
}

.employee-report__markdown :deep(code) {
  font-family: ui-monospace, Consolas, Monaco, 'Courier New', monospace;
  font-size: 0.88em;
  padding: 0.12em 0.4em;
  border-radius: 5px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
  border: 1px solid rgba(15, 23, 42, 0.06);
  word-break: break-word;
}

.employee-report__markdown :deep(pre code) {
  border: none;
  padding: 0;
  background: transparent;
  font-size: inherit;
}

.employee-report__markdown :deep(hr) {
  margin: 14px 0;
  border: none;
  border-top: 1px solid rgba(15, 76, 129, 0.12);
}

.employee-report .raw-block {
  margin: 12px 18px 16px;
}

.raw-block {
  margin-top: 10px;
  color: rgba(23, 32, 51, 0.68);
  font-size: 13px;
}

.raw-block pre {
  white-space: pre-wrap;
  word-break: break-word;
  background: #0f172a;
  color: #dbeafe;
  border-radius: 10px;
  padding: 12px;
  max-height: 360px;
  overflow: auto;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 14px;
  font-size: 13px;
}

.data-table th,
.data-table td {
  text-align: left;
  padding: 10px;
  border-bottom: 1px solid rgba(15, 76, 129, 0.08);
}

.data-table th {
  color: rgba(23, 32, 51, 0.6);
  background: rgba(24, 144, 255, 0.06);
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 9px;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.btn-sm {
  padding: 5px 12px;
  font-size: 12px;
}

.btn-primary {
  background: #1890ff;
  color: #fff;
}

.btn-secondary {
  background: rgba(24, 144, 255, 0.1);
  color: #1890ff;
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  max-width: min(100%, 560px);
}

.identity-hint {
  flex: 1 1 100%;
  margin: 0;
  padding: 0 2px;
  font-size: 12px;
  color: #475569;
  line-height: 1.55;
  text-align: right;
}

.identity-hint code {
  font-size: 11px;
  word-break: break-all;
}

.identity-hint__link {
  margin-left: 6px;
  font-weight: 600;
  color: #2563eb;
  text-decoration: underline;
}

.identity-hint__link:hover {
  color: #1d4ed8;
}

.identity-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 10px;
  background: linear-gradient(135deg, #eef2ff 0%, #e0e7ff 100%);
  border: 1px solid rgba(99, 102, 241, 0.25);
  font-size: 13px;
  font-weight: 700;
  color: #4338ca;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s, box-shadow 0.15s;
}

.identity-badge:hover {
  background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.18);
}

.identity-badge:active {
  transform: scale(0.97);
}

.identity-badge code {
  font-family: Consolas, Monaco, monospace;
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 2px;
  color: #312e81;
  background: rgba(255, 255, 255, 0.7);
  padding: 2px 8px;
  border-radius: 6px;
}

.identity-badge i {
  color: #6366f1;
}

.pill,
.status-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 800;
  background: #e8f3ff;
  color: #1890ff;
}

.pill.ok,
.badge-ok {
  background: #e6f9f0;
  color: #10b759;
}

.pill.warn,
.badge-warn {
  background: #fff7e0;
  color: #d97706;
}

.badge-dim {
  background: #f0f0f0;
  color: #888;
}

.empty-hint,
.error-hint {
  text-align: center;
  padding: 18px;
  color: rgba(23, 32, 51, 0.48);
}

.error-hint {
  color: #b91c1c;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 12px;
}

.mono {
  font-family: Consolas, Monaco, monospace;
}

.small {
  font-size: 12px;
}

@media (max-width: 980px) {
  .digest-layout,
  .allhands-controls {
    grid-template-columns: 1fr;
  }
}
</style>
