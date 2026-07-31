<template>
  <main class="founder-view" id="view-founder-autonomy">
    <header class="founder-hero">
      <div>
        <p class="eyebrow">FOUNDER MODE · STRATEGIC ONLY</p>
        <h1>创始人自治驾驶舱</h1>
        <p class="hero-copy">日常运营交给 AI 员工与 Loops；这里只保留战略方向、少量例外与 veto。</p>
      </div>
      <div class="hero-actions">
        <span class="refresh-time">{{ generatedAtLabel }}</span>
        <button class="refresh-button" type="button" :disabled="loading" @click="refresh">
          <i class="fa fa-refresh" :class="{ 'fa-spin': loading }" aria-hidden="true"></i>
          {{ loading ? '正在刷新证据' : '刷新真实进度' }}
        </button>
      </div>
    </header>

    <section v-if="error" class="error-panel" role="alert">
      <strong>驾驶舱暂时无法读取：</strong>{{ error }}
    </section>

    <template v-if="snapshot">
      <section class="overview-grid" aria-label="自治总览">
        <article class="overall-card">
          <div class="overall-score">{{ snapshot.overall_progress }}<small>%</small></div>
          <div class="overall-copy">
            <span>距离创始人退出日常运营还差</span>
            <strong>{{ snapshot.overall_remaining }}%</strong>
            <p>总分是七项能力的等权平均，缺少运行或生产证据时不会自动补分。</p>
          </div>
        </article>

        <article class="attention-card" :class="{ clear: snapshot.attention?.human_intervention_rare }">
          <div class="section-title-row">
            <div>
              <span class="section-kicker">只需要你处理</span>
              <h2>{{ snapshot.attention?.human_intervention_rare ? '当前无高频人工负担' : `${snapshot.attention?.total || 0} 项例外信号` }}</h2>
            </div>
            <span class="attention-badge">{{ snapshot.attention?.human_intervention_rare ? '低频' : '需关注' }}</span>
          </div>
          <ul v-if="snapshot.attention?.items?.length" class="attention-list">
            <li v-for="item in snapshot.attention.items" :key="`${item.kind}-${item.label}`">
              <router-link :to="attentionRoute(item)">
                <span>{{ item.label }}</span>
                <strong>{{ item.count }}</strong>
              </router-link>
            </li>
          </ul>
          <p v-else class="empty-copy">没有待审批、治理 hold 或悬挂 Loop。</p>
        </article>
      </section>

      <section v-if="blockingGateKeys.length" class="blocking-banner">
        <i class="fa fa-shield" aria-hidden="true"></i>
        <div>
          <strong>系统正在正确地阻止自己继续：</strong>
          <span>{{ blockingGateKeys.join(' / ') }}。解除前不计为“无人介入完成”。</span>
        </div>
        <router-link :to="{ name: 'duty-roster-graph', query: { view: 'loop' } }">查看 Loop 证据</router-link>
      </section>

      <section class="quick-links" aria-label="创始人控制面入口">
        <router-link :to="{ name: 'autonomy-approval-hub' }">
          <i class="fa fa-check-square-o" aria-hidden="true"></i>
          <span><strong>审批中心</strong><small>少量例外与 veto</small></span>
        </router-link>
        <router-link :to="{ name: 'persy-knowledge' }">
          <i class="fa fa-book" aria-hidden="true"></i>
          <span><strong>知识库</strong><small>事实、资料与长期记忆</small></span>
        </router-link>
        <router-link :to="{ name: 'workflow-employee-space' }">
          <i class="fa fa-users" aria-hidden="true"></i>
          <span><strong>AI 员工</strong><small>岗位、工位与执行状态</small></span>
        </router-link>
        <router-link :to="{ name: 'duty-roster-graph', query: { view: 'loop' } }">
          <i class="fa fa-repeat" aria-hidden="true"></i>
          <span><strong>Goals & Loops</strong><small>目标、执行与闭环账本</small></span>
        </router-link>
      </section>

      <section class="council-panel" :class="{ ready: snapshot.live_summary?.strategic_council_ready }" aria-label="战略三席">
        <div class="section-title-row">
          <div>
            <span class="section-kicker">战略三席 · 同一证据回执</span>
            <h2>Persy 记事实，Para 跑目标，Retort 先反问再放行</h2>
          </div>
          <span class="council-state">{{ snapshot.live_summary?.strategic_council_ready ? '已打通' : '等待真实回执' }}</span>
        </div>
        <div class="council-grid">
          <article v-for="role in councilRoles" :key="role.key">
            <span>{{ role.eyebrow }}</span>
            <strong>{{ role.name }}</strong>
            <p>{{ role.responsibility }}</p>
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

      <section class="score-section">
        <div class="section-heading">
          <div>
            <span class="section-kicker">七项真实进度</span>
            <h2>源码能力、运行证据、部署证据、客户价值分层计算</h2>
          </div>
          <span class="schema-tag">{{ snapshot.schema_version }}</span>
        </div>

        <div class="dimension-grid">
          <article v-for="dimension in snapshot.dimensions" :key="dimension.id" class="dimension-card" :class="`is-${dimension.status}`">
            <header>
              <div>
                <span class="dimension-label">{{ dimension.label }}</span>
                <strong>{{ dimension.progress }}%</strong>
              </div>
              <span class="status-chip">{{ dimension.status_label }}</span>
            </header>
            <div class="progress-track" :aria-label="`${dimension.label} ${dimension.progress}%`">
              <span :style="{ width: `${dimension.progress}%` }"></span>
            </div>
            <p class="target-copy">{{ dimension.target }}</p>
            <div class="next-gap">
              <span>还差 {{ dimension.remaining }}%</span>
              <strong>{{ dimension.next_gap }}</strong>
            </div>
            <details>
              <summary>查看 {{ dimension.passed_gate_count }}/{{ dimension.total_gate_count }} 项证据门槛</summary>
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
            </details>
          </article>
        </div>
      </section>

      <section class="evidence-section">
        <article class="live-card">
          <div class="section-title-row">
            <div>
              <span class="section-kicker">当前运行真相</span>
              <h2>不是源码声明</h2>
            </div>
            <span class="live-dot" :class="{ ok: snapshot.live_summary?.runtime_fresh }"></span>
          </div>
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
          <span class="section-kicker">证据域</span>
          <h2>哪些层已经有证据</h2>
          <ul class="truth-list">
            <li v-for="(item, key) in snapshot.truth_domains" :key="key" :class="{ ok: item.available }">
              <i class="fa" :class="item.available ? 'fa-check-circle' : 'fa-circle-o'" aria-hidden="true"></i>
              <span>{{ item.label }}</span>
              <strong>{{ item.available ? '有证据' : '待证明' }}</strong>
            </li>
          </ul>
          <p v-if="snapshot.warnings?.length" class="warning-copy">部分数据源不可用：{{ snapshot.warnings.join('；') }}</p>
        </article>
      </section>
    </template>
    <section v-else-if="loading" class="loading-panel">正在汇总审批、知识库、员工、Goals 与 Loop 账本……</section>
  </main>
</template>

<script setup lang="ts">
import './FounderAutonomyView.extracted.css'
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
    { key: 'persy', eyebrow: '拟人', name: 'Persy', responsibility: '从知识库提供事实、历史与长期记忆', expected: 'grounded' },
    { key: 'para', eyebrow: '排比', name: 'Para', responsibility: '把战略绑定到真实 Goal、Loop 与执行任务', expected: 'linked' },
    { key: 'retort', eyebrow: '反问', name: 'Retort', responsibility: '意图不清先澄清（Boss 问答页），未对齐或未回答就阻止部署', expected: 'aligned' },
  ]
  return rows.map((row) => {
    const detail = roles[row.key] || {}
    const status = String(detail.status || 'awaiting_receipt')
    return { ...row, status, ready: status === row.expected }
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


