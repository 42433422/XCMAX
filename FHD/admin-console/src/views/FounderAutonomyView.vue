<template>
  <main class="founder-view page-content admin-screen" id="view-founder-autonomy">
    <header class="founder-hero page-header">
      <div>
        <h1>创始人状态</h1>
      </div>
      <div class="hero-actions">
        <span class="refresh-time">{{ generatedAtLabel }}</span>
        <button class="refresh-button" type="button" :disabled="loading" @click="refresh">
          <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <section v-if="error" class="error-panel" role="alert">
      <strong>状态读取失败：</strong>{{ error }}
    </section>

    <template v-if="snapshot">
      <p v-if="snapshot.warnings?.length" class="warning-copy" role="status">数据源异常：{{ snapshot.warnings.join('；') }}</p>
      <section class="metric-strip" aria-label="核心指标">
        <article class="metric-tile primary">
          <span>总体进度</span><strong>{{ snapshot.overall_progress ?? '—' }}<small>%</small></strong>
          <div class="metric-track" aria-hidden="true"><span :style="{ width: `${snapshot.overall_progress || 0}%` }"></span></div>
        </article>
        <article class="metric-tile" :class="{ warning: snapshot.attention?.total > 0 }">
          <span>例外信号</span><strong>{{ snapshot.attention?.total ?? '—' }}<small>项</small></strong>
          <span class="metric-status">{{ snapshot.attention?.human_intervention_rare === true ? '人工介入低频' : snapshot.attention?.total > 0 ? '需关注' : '待核实' }}</span>
        </article>
        <article class="metric-tile">
          <span>生产履职员工</span><strong>{{ snapshot.live_summary?.production_proven_employees ?? '—' }}<small>/ {{ snapshot.live_summary?.planned_employees ?? '—' }}</small></strong>
          <span class="metric-status">{{ snapshot.live_summary?.employee_production_workforce_ready === true ? '已达门槛' : snapshot.live_summary?.employee_production_workforce_ready === false ? '未达门槛' : '待核实' }}</span>
        </article>
        <article class="metric-tile">
          <span>客户验收</span><strong>{{ snapshot.live_summary?.paid_acceptance_count ?? '—' }}<small>项</small></strong>
          <span class="metric-status">{{ snapshot.live_summary?.customer_value_ledger_ready === true ? '账本已就绪' : snapshot.live_summary?.customer_value_ledger_ready === false ? '账本未就绪' : '待核实' }}</span>
        </article>
      </section>

      <section v-if="blockingGateKeys.length" class="blocking-banner">
        <i class="fa fa-shield" aria-hidden="true"></i>
        <div>
          <strong>自治阻塞：</strong>
          <span>{{ blockingGateKeys.join(' / ') }}</span>
        </div>
        <router-link :to="{ name: 'duty-roster-graph', query: { view: 'loop' } }">查看详情</router-link>
      </section>

      <AdminSectionNav v-model="section" label="创始人状态分区" :items="[{ value: 'status', label: '状态总览' }, { value: 'council', label: '战略协作' }, { value: 'evidence', label: '运行证据' }]" />
      <div class="admin-pane founder-pane" tabindex="0" aria-label="状态内容">
      <div v-show="section === 'status'" class="dashboard-body">
      <section class="score-section">
        <div class="section-heading"><h2>七项状态</h2><span>进度 / 状态</span></div>

        <div class="dimension-grid">
          <details v-for="dimension in snapshot.dimensions" :key="dimension.id" class="dimension-row" :class="`is-${dimension.status}`">
            <summary class="dimension-summary">
              <span class="dimension-label">{{ dimension.label }}</span>
              <div class="progress-track" :aria-label="`${dimension.label} ${dimension.progress}%`"><span :style="{ width: `${dimension.progress}%` }"></span></div>
              <strong>{{ dimension.progress }}%</strong>
              <span class="status-chip">{{ dimension.status_label }}</span>
            </summary>
            <div class="dimension-detail">
              <p class="next-gap">{{ dimension.next_gap }}</p>
              <h3>证据 {{ dimension.passed_gate_count }}/{{ dimension.total_gate_count }}</h3>
              <div class="gate-columns">
                <div>
                  <h3>已证明</h3>
                  <ul>
                    <li v-for="gate in dimension.evidence" :key="gate.key">
                      <span>{{ gate.label }} · {{ gate.weight }}%</span>
                      <small>{{ gate.evidence }}</small>
                    </li>
                    <li v-if="!dimension.evidence?.length" class="muted">暂无可计分证据</li>
                  </ul>
                </div>
                <div>
                  <h3>未闭环</h3>
                  <ul>
                    <li v-for="gate in dimension.gaps" :key="gate.key">
                      <span>{{ gate.label }} · {{ gate.weight }}%</span>
                      <small>{{ gate.gap }}</small>
                    </li>
                    <li v-if="!dimension.gaps?.length" class="muted">当前门槛已全部满足</li>
                  </ul>
                </div>
              </div>
            </div>
          </details>
        </div>
      </section>

        <aside class="action-column" aria-label="待关注与常用入口">
        <article class="attention-card" :class="{ clear: snapshot.attention?.human_intervention_rare }">
          <div class="section-title-row">
            <div>
              <h2>待关注事项</h2>
            </div>
            <span class="attention-badge">{{ snapshot.attention?.human_intervention_rare ? '低频' : '需关注' }}</span>
          </div>
          <ul v-if="snapshot.attention?.items?.length" class="attention-list">
            <li v-for="item in snapshot.attention.items" :key="`${item.kind}-${item.label}`">
              <router-link :to="attentionRoute(item)">
                <span>{{ item.label }}</span>
                <strong>{{ item.count }}<i class="fa fa-angle-right" aria-hidden="true"></i></strong>
              </router-link>
            </li>
          </ul>
          <p v-else class="empty-copy">没有待审批、治理 hold 或悬挂 Loop。</p>
        </article>
          <section class="shortcut-panel"><h2>常用入口</h2>
      <nav class="quick-links" aria-label="创始人控制面入口">
        <router-link :to="{ name: 'autonomy-approval-hub' }">
          <i class="fa fa-check-square-o" aria-hidden="true"></i>
          <span><strong>审批中心</strong></span>
        </router-link>
        <router-link :to="{ name: 'persy-knowledge' }">
          <i class="fa fa-book" aria-hidden="true"></i>
          <span><strong>知识库</strong></span>
        </router-link>
        <router-link :to="{ name: 'workflow-employee-space' }">
          <i class="fa fa-users" aria-hidden="true"></i>
          <span><strong>AI 员工</strong></span>
        </router-link>
        <router-link :to="{ name: 'duty-roster-graph', query: { view: 'loop' } }">
          <i class="fa fa-repeat" aria-hidden="true"></i>
          <span><strong>目标与执行</strong></span>
        </router-link>
      </nav>

          </section>
        </aside>
      </div>

      <section v-show="section === 'council'" class="council-panel" :class="{ ready: snapshot.live_summary?.strategic_council_ready }" aria-label="战略三席">
        <h2 class="pane-title">战略协作 <span class="council-state">{{ snapshot.live_summary?.strategic_council_ready ? '已打通' : '待回执' }}</span></h2>
        <div class="council-grid">
          <article v-for="role in councilRoles" :key="role.key">
            <span>{{ role.eyebrow }}</span>
            <strong>{{ role.name }}</strong>
            <small :class="{ ok: role.ready }">{{ role.status }}</small>
          </article>
        </div>
        <dl class="council-links">
          <div><dt>Goal</dt><dd>{{ snapshot.live_summary?.strategic_council_latest?.goal_id || '未绑定' }}</dd></div>
          <div><dt>Loop</dt><dd>{{ snapshot.live_summary?.strategic_council_latest?.loop_run_id || '未绑定' }}</dd></div>
          <div><dt>Para task</dt><dd>{{ snapshot.live_summary?.strategic_council_latest?.para_task_id || '未绑定' }}</dd></div>
          <div><dt>验证回执</dt><dd>{{ snapshot.live_summary?.strategic_council_receipts || 0 }} 条</dd></div>
          <div>
            <dt>Retort 澄清</dt>
            <dd :class="{ warn: !snapshot.live_summary?.retort_clarifications_healthy }">
              <template v-if="snapshot.live_summary?.retort_clarifications_healthy">队列健康</template>
              <template v-else>
                待答 {{ snapshot.live_summary?.retort_clarifications_open || 0 }}
                <template v-if="snapshot.live_summary?.retort_clarifications_critical">
                  · 即将超时 {{ snapshot.live_summary.retort_clarifications_critical }}
                </template>
                ·
                <router-link :to="{ name: 'employee-autonomy', query: { tab: 'questions' } }">去问答</router-link>
              </template>
            </dd>
          </div>
        </dl>
      </section>

      <section v-show="section === 'evidence'" class="evidence-section">
        <h2 class="pane-title">运行与证据明细</h2>
        <article class="live-card">
          <h2>运行指标</h2>
          <dl class="live-metrics">
            <div><dt>最新事件</dt><dd>{{ formatDate(snapshot.live_summary?.latest_event_at) }}</dd></div>
            <div><dt>最近完成</dt><dd>{{ snapshot.live_summary?.latest_complete_status || '无证据' }}</dd></div>
            <div><dt>自治门禁</dt><dd>{{ snapshot.live_summary?.active_gates_ok ? '通过' : '阻塞' }}</dd></div>
            <div><dt>治理健康</dt><dd>{{ snapshot.live_summary?.governance_ok ? '健康' : '需复盘' }}</dd></div>
            <div><dt>登记编制</dt><dd>{{ snapshot.live_summary?.registered_employees || 0 }}/{{ snapshot.live_summary?.planned_employees || 0 }}</dd></div>
            <div><dt>已有任务合同</dt><dd>{{ snapshot.live_summary?.assigned_employees || 0 }}/{{ snapshot.live_summary?.planned_employees || 0 }}</dd></div>
            <div><dt>能力回执（含演练）</dt><dd>{{ snapshot.live_summary?.proven_employees || 0 }}/{{ snapshot.live_summary?.planned_employees || 0 }}</dd></div>
            <div><dt>burn-in 演练回执</dt><dd>{{ snapshot.live_summary?.burn_in_proven_employees || 0 }}/{{ snapshot.live_summary?.planned_employees || 0 }}</dd></div>
            <div><dt>生产履职回执（不含演练）</dt><dd>{{ snapshot.live_summary?.production_proven_employees || 0 }}/{{ snapshot.live_summary?.planned_employees || 0 }}</dd></div>
            <div><dt>生产履职门槛</dt><dd>{{ snapshot.live_summary?.employee_production_workforce_ready ? '已达到 80%' : '未达到 80%' }}</dd></div>
            <div><dt>空壳/无效 handler</dt><dd>{{ snapshot.live_summary?.shell_employees || 0 }} 名</dd></div>
            <div><dt>AI 员工主模型</dt><dd>{{ platformLlmLabel }}</dd></div>
            <div><dt>未解决死信</dt><dd>{{ snapshot.live_summary?.unresolved_dead_letters || 0 }} 条</dd></div>
            <div><dt>已审计处理死信</dt><dd>{{ snapshot.live_summary?.resolved_dead_letters || 0 }} 条</dd></div>
            <div><dt>Loop 员工</dt><dd>{{ snapshot.live_summary?.loop_participants || 0 }} 名</dd></div>
            <div><dt>Goals</dt><dd>{{ snapshot.live_summary?.goals_closed || 0 }}/{{ snapshot.live_summary?.goals_total || 0 }} 完成</dd></div>
            <div><dt>客户价值账本</dt><dd>{{ snapshot.live_summary?.customer_value_ledger_ready ? '权威只追加' : '未就绪' }}</dd></div>
            <div><dt>外部客户目标</dt><dd>{{ snapshot.live_summary?.customer_goals || 0 }} 项</dd></div>
            <div><dt>不可变产物交付</dt><dd>{{ snapshot.live_summary?.customer_deliveries || 0 }} 项</dd></div>
            <div><dt>缺少制品证明</dt><dd>{{ snapshot.live_summary?.unproven_customer_deliveries || 0 }} 项</dd></div>
            <div><dt>付费交付闭环</dt><dd>{{ snapshot.live_summary?.paid_delivery_count || 0 }} 项</dd></div>
            <div><dt>客户明确验收</dt><dd>{{ snapshot.live_summary?.paid_acceptance_count || 0 }} 项</dd></div>
            <div><dt>已排除非真实记录</dt><dd>{{ excludedCustomerRecords }} 条</dd></div>
            <div><dt>自治审计账本</dt><dd>{{ snapshot.live_summary?.autonomy_audit_authoritative ? `权威只追加 · ${snapshot.live_summary?.autonomy_audit_count || 0} 条` : '未证明' }}</dd></div>
            <div><dt>禁止项后验覆盖</dt><dd>{{ prohibitedCoverageLabel }}</dd></div>
            <div><dt>veto 通道</dt><dd>{{ snapshot.live_summary?.veto_channel_available ? `可用 · 待处理 ${snapshot.live_summary?.veto_pending || 0}` : '未部署验证' }}</dd></div>
            <div><dt>MODstore 已验证部署</dt><dd>{{ snapshot.live_summary?.verified_modstore_deployments || 0 }} 次</dd></div>
            <div><dt>知识库</dt><dd>{{ snapshot.live_summary?.knowledge_documents || 0 }} 文档 · {{ snapshot.live_summary?.knowledge_chunks || 0 }} chunks</dd></div>
            <div><dt>第三方核验付费</dt><dd>{{ snapshot.live_summary?.paid_count || 0 }} 笔</dd></div>
            <div><dt>生产部署验证</dt><dd>{{ snapshot.live_summary?.deploy_verified ? '已证明' : '未证明' }}</dd></div>
          </dl>
        </article>
        <article class="truth-card">
          <h2>证据来源</h2>
          <ul class="truth-list">
            <li v-for="(item, key) in snapshot.truth_domains" :key="key" :class="{ ok: item.available }">
              <i class="fa" :class="item.available ? 'fa-check-circle' : 'fa-circle-o'" aria-hidden="true"></i>
              <span>{{ item.label }}</span>
              <strong>{{ item.available ? '有证据' : '待证明' }}</strong>
            </li>
          </ul>
        </article>
      </section>
      </div>
    </template>
    <section v-else-if="loading" class="loading-panel">正在汇总审批、知识库、员工、Goals 与 Loop 账本……</section>
  </main>
</template>

<script setup lang="ts">
import AdminSectionNav from '../components/admin/AdminSectionNav.vue'
const section = ref('status')
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { xcmaxOpsApi } from '@/api/xcmaxOps'

type FounderSnapshot = Record<string, any>

const snapshot = ref<FounderSnapshot | null>(null)
const loading = ref(false)
const error = ref('')
let timer: number | null = null

const generatedAtLabel = computed(() => {
  if (!snapshot.value?.generated_at) return '尚未刷新'
  return `证据时间 ${formatDate(snapshot.value.generated_at)}`
})

const platformLlmLabel = computed(() => {
  const route = snapshot.value?.live_summary?.platform_llm
  if (!route?.configured) return '未配置'
  return `${route.provider || '未知'} / ${route.model || '未知'}`
})

const excludedCustomerRecords = computed(() => {
  const excluded = snapshot.value?.live_summary?.customer_value_excluded
  if (!excluded || typeof excluded !== 'object') return 0
  return Object.values(excluded).reduce((total, value) => {
    const count = Number(value)
    return total + (Number.isFinite(count) ? count : 0)
  }, 0)
})

const prohibitedCoverageLabel = computed(() => {
  const summary = snapshot.value?.live_summary
  const status = String(summary?.prohibited_miss_status || 'unknown')
  const coverage = Number(summary?.prohibited_posthoc_coverage_rate || 0)
  if (status === 'detected') return `发现漏放 · 覆盖 ${coverage}%`
  if (status === 'verified_clear') return `已验证零漏放 · 覆盖 ${coverage}%`
  return `证据不足 · 覆盖 ${coverage}%`
})

const blockingGateKeys = computed<string[]>(() =>
  Array.isArray(snapshot.value?.live_summary?.blocking_gate_keys)
    ? snapshot.value.live_summary.blocking_gate_keys.filter(Boolean)
    : [],
)

const councilRoles = computed(() => {
  const roles = snapshot.value?.live_summary?.strategic_council_roles || {}
  const rows = [
    { key: 'persy', eyebrow: '拟人', name: 'Persy', expected: 'grounded' },
    { key: 'para', eyebrow: '排比', name: 'Para', expected: 'linked' },
    { key: 'retort', eyebrow: '反问', name: 'Retort', expected: 'aligned' },
  ]
  return rows.map((row) => {
    const detail = roles[row.key] || {}
    const status = String(detail.status || 'awaiting_receipt')
    return { ...row, status: ({ grounded: '已核实', linked: '已关联', aligned: '已对齐', awaiting_receipt: '待回执' } as Record<string, string>)[status] || status, ready: status === row.expected }
  })
})

function formatDate(value: unknown): string {
  const raw = String(value || '').trim()
  if (!raw) return '无证据'
  const dt = new Date(raw)
  if (Number.isNaN(dt.getTime())) return raw
  return dt.toLocaleString('zh-CN', { hour12: false })
}

function attentionRoute(item: Record<string, any>) {
  const requestedName = String(item.route || 'founder-autonomy')
  return {
    name: requestedName === 'approval-hub' ? 'autonomy-approval-hub' : requestedName,
    query: item.query && typeof item.query === 'object' ? item.query : undefined,
  }
}

async function refresh() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await xcmaxOpsApi.founderAutonomyStatus() as Record<string, any>
    const data = response?.data || response
    if (!data?.dimensions) throw new Error(response?.message || '后端未返回七项进度')
    snapshot.value = data
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err || '读取失败')
  } finally {
    loading.value = false
  }
}

function startPolling() {
  if (timer != null) return
  timer = window.setInterval(refresh, 30_000)
}

function stopPolling() {
  if (timer == null) return
  window.clearInterval(timer)
  timer = null
}

onMounted(() => {
  void refresh()
  startPolling()
})
onActivated(() => {
  void refresh()
  startPolling()
})
onDeactivated(stopPolling)
onBeforeUnmount(stopPolling)
</script>

<style scoped src="./FounderAutonomyView.css"></style>
