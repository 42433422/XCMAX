import { computed, reactive } from 'vue'
import type { SelfEvolutionRuntimePanelState } from './useSelfEvolutionRuntimePanelState'
import type { AnyRecord } from './useLoopRuntimePanel'

/**
 * 自进化循环运行面板的展示层状态。
 * 把 `useSelfEvolutionRuntimePanelState` 解析出的领域状态，
 * 收敛为模板可直接渲染的卡片数组 / 阶段 / 标签（statusTone、decisionCards、
 * loopStages、proactiveCards、rosterAlignmentCards 等）。
 *
 * 注意：`state` 是 reactive 对象，其属性访问会自动解包 ref。因此这里必须在
 * computed 求值函数内部通过 `state.xxx` 读取，以保持响应式；不能在函数顶部
 * 解构 reactive 值（会退化为一次性快照）。
 */
export function useSelfEvolutionRuntimePresenters(state: SelfEvolutionRuntimePanelState) {
  // 纯函数工具稳定不变，可安全解构；reactive 值一律在 computed 内经 state.xxx 读取。
  const { asRecord, asArray, asString, asNumber, firstText } = state

  const statusTone = computed(() => {
    if (state.error) return 'bad'
    if (state.openRunIds.length > 0) return 'running'
    if (state.gate.should_run === true) return 'warn'
    if (asString(state.latestComplete.phase) === 'complete') return 'ok'
    return 'idle'
  })

  const statusLabel = computed(() => {
    if (state.error) return '接口异常'
    if (state.openRunIds.length > 0) return '运行中'
    if (state.gate.should_run === true) return '达到触发阈值'
    if (asString(state.gate.reason) === 'cooldown') return '冷却中'
    if (asString(state.latestComplete.phase) === 'complete') return '最近完成'
    return '待命'
  })

  const cronLine = computed(() => {
    const hour = asNumber(state.cron.hour, 3)
    const minute = asNumber(state.cron.minute, 0)
    const tz = firstText(state.cron.timezone, 'Asia/Shanghai')
    return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${tz}`
  })

  const signalCount = computed(() => asNumber(state.gate.signal_count, 0))
  const threshold = computed(() => asNumber(state.gate.threshold, asNumber(state.policy.threshold, 1)))
  const riskScore = computed(() => {
    const v3 = asRecord(state.decision.safety_score_v3)
    const v2 = asRecord(state.decision.safety_score_v2)
    const v1 = asRecord(state.decision.risk_score)
    if (v3.score != null) return { label: 'V3 安全分', value: asNumber(v3.score), goodHigh: true }
    if (v2.score != null) return { label: 'V2 安全分', value: asNumber(v2.score), goodHigh: true }
    if (v1.score != null) return { label: 'V1 风险分', value: asNumber(v1.score), goodHigh: false }
    return null
  })
  const qaVerdict = computed(() => {
    const qa = asRecord(state.decision.qa)
    const reviewGate = asRecord(state.decision.structured_gate)
    return firstText(qa.verdict, reviewGate.qa_verdict, state.lastRun.qa_verdict, '待回写')
  })

  const evidenceCards = computed(() => [
    { label: 'Para 任务', value: state.paraTaskId || '无进行中任务' },
    { label: '待处理项', value: String(state.openItems.length) },
    { label: '最近运行', value: String(state.recentRuns.length) },
    { label: '冷却', value: `${asNumber(state.policy.cooldown_minutes, 360)} 分钟` },
  ])

  const decisionCards = computed(() => {
    const md = state.mergeDecision
    const cards = [
      {
        key: 'action',
        label: '动作',
        value: firstText(md.action, '等待决策'),
        sub: firstText(md.reason, '策略待定'),
      },
    ]
    const v1 = asRecord(md.risk_score_v1)
    const v2 = asRecord(md.safety_score_v2)
    const v3 = asRecord(md.safety_score_v3)
    const roster = asRecord(md.roster_gate)
    const governance = Object.keys(asRecord(md.governance_gate)).length
      ? asRecord(md.governance_gate)
      : state.currentGovernanceGate
    const evolution = asRecord(md.evolution_gate)
    if (v1.score != null) cards.push({
      key: 'v1',
      label: 'V1 风险分',
      value: String(v1.score),
      sub: `最大 ${v1.max_allowed ?? '—'} · ${firstText(v1.reason, v1.source, '')}`,
    })
    if (v2.score != null) cards.push({
      key: 'v2',
      label: 'V2 安全分',
      value: String(v2.score),
      sub: `最小 ${v2.min_allowed ?? '—'} · ${firstText(v2.reason, v2.source, '')}`,
    })
    if (v3.score != null) cards.push({
      key: 'v3',
      label: 'V3 安全分',
      value: String(v3.score),
      sub: `最小 ${v3.min_allowed ?? '—'} · ${firstText(v3.reason, v3.source, '')}`,
    })
    if (md.qa_verdict || md.review_max_severity) cards.push({
      key: 'qa',
      label: 'QA / 审查',
      value: firstText(md.qa_verdict, '—'),
      sub: md.review_max_severity ? `审查 ${md.review_max_severity}` : '结构化检查',
    })
    if (Object.keys(roster).length) cards.push({
      key: 'roster',
      label: '排班检查',
      value: firstText(roster.action, roster.ok === true ? '允许' : '异常'),
      sub: firstText(roster.reason, roster.policy, '排班策略'),
    })
    if (Object.keys(governance).length) cards.push({
      key: 'governance',
      label: '管理检查',
      value: firstText(governance.action, governance.ok === true ? '允许' : '异常'),
      sub: firstText(
        governance.reason,
        asRecord(governance.summary).health,
        governance.policy,
        '审计策略',
      ),
    })
    if (Object.keys(evolution).length) cards.push({
      key: 'evolution',
      label: '进化检查',
      value: evolution.pause === true ? '暂停' : '允许',
      sub: firstText(evolution.reason, `历史 ${evolution.history_count ?? 0}`, '进化策略'),
    })
    return cards
  })

  const loopStages = computed(() => [
    {
      key: 'signals',
      title: '信号感知',
      value: `${signalCount.value}/${threshold.value}`,
      meta: firstText(state.gate.reason, '未达标'),
      tone: signalCount.value >= threshold.value ? 'warn' : 'idle',
    },
    {
      key: 'incident',
      title: '异常记录',
      value: String(asNumber(state.gate.incident_count, 0)),
      meta: `${asNumber(state.gate.lookback_hours, 24)}h 窗口`,
      tone: asNumber(state.gate.incident_count, 0) > 0 ? 'running' : 'idle',
    },
    {
      key: 'team',
      title: '三员工执行',
      value: state.openRunIds.length ? `${state.openRunIds.length} 轮` : '待命',
      meta: '侦察 / 修复 / QA',
      tone: state.openRunIds.length ? 'running' : 'idle',
    },
    {
      key: 'qa',
      title: 'QA JSON',
      value: qaVerdict.value,
      meta: '结构化检查',
      tone: qaVerdict.value === 'PASS' ? 'ok' : qaVerdict.value === 'FAIL' ? 'bad' : 'idle',
    },
    {
      key: 'risk',
      title: '风险检查',
      value: riskScore.value ? String(riskScore.value.value) : '待评分',
      meta: riskScore.value?.label || 'V1/V2/V3',
      tone: riskScore.value ? 'ok' : 'idle',
    },
    {
      key: 'merge',
      title: '合并/审批',
      value: state.actionLabel,
      meta: state.branchName || '分支待回写',
      tone: /merge|merged|pass|auto/i.test(state.actionLabel) ? 'ok' : 'idle',
    },
  ])

  const kbCards = computed(() => {
    const kb = state.kbSummary
    const redis = asRecord(kb.redisvl_status)
    return [
      {
        key: 'redisvl',
        label: 'RedisVL',
        value: redis.ready === true ? '就绪' : '未就绪',
        sub: firstText(redis.reason, redis.error, redis.backend, '向量索引'),
        tone: redis.ready === true ? 'ok' : 'warn',
      },
      {
        key: 'fix',
        label: '修复知识命中',
        value: String(asNumber(kb.fix_hit_count, 0)),
        sub: firstText(kb.engine, '知识库搜索'),
        tone: asNumber(kb.fix_hit_count, 0) > 0 ? 'ok' : 'idle',
      },
      {
        key: 'pattern',
        label: '代码模式命中',
        value: String(asNumber(kb.pattern_hit_count, 0)),
        sub: firstText(kb.kb_root, 'FHD/XCAGI/kb'),
        tone: asNumber(kb.pattern_hit_count, 0) > 0 ? 'ok' : 'idle',
      },
    ]
  })

  const kbHitLines = computed(() => {
    const fixes = asArray(state.kbSummary.top_fix_hits).map((item) => {
      const row = asRecord(item)
      return firstText(row.symptom, row.root_cause, row.path)
    }).filter(Boolean)
    const patterns = asArray(state.kbSummary.top_pattern_hits).map((item) => {
      const row = asRecord(item)
      return firstText(row.summary, row.pattern, row.path)
    }).filter(Boolean)
    return [...fixes, ...patterns].slice(0, 5)
  })

  const kbFixHitDetails = computed(() =>
    asArray(state.kbSummary.top_fix_hits).map((item) => asRecord(item)).slice(0, 3),
  )

  const kbPatternHitDetails = computed(() =>
    asArray(state.kbSummary.top_pattern_hits).map((item) => asRecord(item)).slice(0, 3),
  )

  const proactiveSignals = computed<AnyRecord>(() => asRecord(state.gate.proactive_signals))
  const proactiveCandidates = computed(() =>
    asArray(proactiveSignals.value.candidates)
      .map((item) => asRecord(item))
      .slice(0, 6),
  )

  const proactiveCards = computed(() => {
    const count = asNumber(state.gate.proactive_task_count, proactiveCandidates.value.length)
    const kinds = new Set(
      proactiveCandidates.value
        .map((item) => firstText(item.task_type, item.kind, item.category, item.signal_type))
        .filter(Boolean),
    )
    return [
      {
        key: 'count',
        label: '主动优化候选',
        value: String(count),
        sub: count > 0 ? '已进入自进化信号池' : '暂无候选',
        tone: count > 0 ? 'ok' : 'idle',
      },
      {
        key: 'types',
        label: '任务类型',
        value: String(kinds.size),
        sub: Array.from(kinds).slice(0, 3).join(' / ') || '性能 / 覆盖率 / 债务',
        tone: kinds.size > 0 ? 'ok' : 'idle',
      },
      {
        key: 'source',
        label: '信号源',
        value: firstText(proactiveSignals.value.source, proactiveSignals.value.engine, 'scripts/dev'),
        sub: firstText(proactiveSignals.value.generated_at, proactiveSignals.value.checked_at, '运行时扫描'),
        tone: 'idle',
      },
    ]
  })

  const metricWindows = computed(() =>
    asArray(state.evolutionMetrics.windows).map((item) => asRecord(item)).slice(-2),
  )

  const rosterCoverage = computed(() =>
    asArray(state.rosterAlignment.department_coverage)
      .map((item) => asRecord(item))
      .filter((item) => String(item.key || item.label || '').trim()),
  )

  const rosterGate = computed<AnyRecord>(() => asRecord(state.rosterAlignment.gate))
  const rosterRemediation = computed<AnyRecord>(() => asRecord(state.rosterAlignment.remediation))

  const rosterAlignmentCards = computed(() => {
    const roster = state.rosterAlignment
    return [
      {
        key: 'planned',
        label: '编制基线',
        value: `${roster.planned_count ?? '—'}`,
        sub: firstText(roster.source, 'duty_roster.py'),
        tone: 'ok',
      },
      {
        key: 'participants',
        label: '排班匹配',
        value: `${roster.in_roster_count ?? '—'}`,
        sub: `运行时参与 ${roster.participant_count ?? 0}`,
        tone: Number(roster.in_roster_count || 0) > 0 ? 'run' : 'warn',
      },
      {
        key: 'deployed',
        label: '上岗匹配',
        value: `${roster.in_deployed_count ?? '—'}`,
        sub: `已登记上岗 ${roster.deployed_count ?? 0}`,
        tone: Number(roster.in_deployed_count || 0) > 0 ? 'run' : 'warn',
      },
      {
        key: 'outside',
        label: '非编制混入',
        value: `${roster.out_of_roster_count ?? 0}`,
        sub: asArray(roster.out_of_roster_ids).map((id) => String(id)).filter(Boolean).slice(0, 3).join(' / ') || '未混入',
        tone: Number(roster.out_of_roster_count || 0) > 0 ? 'bad' : 'ok',
      },
      {
        key: 'not-deployed',
        label: '未登记上岗',
        value: `${roster.not_deployed_count ?? 0}`,
        sub: asArray(roster.not_deployed_ids).map((id) => String(id)).filter(Boolean).slice(0, 3).join(' / ') || '全部已登记',
        tone: Number(roster.not_deployed_count || 0) > 0 ? 'bad' : 'ok',
      },
      {
        key: 'coverage',
        label: '部门覆盖',
        value: `${rosterCoverage.value.length}`,
        sub: firstText(roster.status, '排班匹配'),
        tone: rosterCoverage.value.length > 0 ? 'run' : 'warn',
      },
      {
        key: 'gate',
        label: '隔离策略',
        value: firstText(rosterGate.value.action, '—'),
        sub: firstText(rosterGate.value.reason, rosterGate.value.policy, '排班检查'),
        tone: rosterGate.value.blocking === true ? 'bad' : rosterGate.value.action === 'allow' ? 'ok' : 'warn',
      },
    ]
  })

  const evolutionMetricCards = computed(() => {
    const latest = metricWindows.value[metricWindows.value.length - 1] || {}
    const metrics = state.evolutionMetrics
    return [
      {
        key: 'pause',
        label: '自进化状态',
        value: metrics.pause === true ? '暂停' : '允许运行',
        sub: firstText(metrics.reason, '指标检查'),
        tone: metrics.pause === true ? 'bad' : 'ok',
      },
      {
        key: 'coverage',
        label: '覆盖率变化',
        value: latest.coverage_delta == null ? '—' : `${latest.coverage_delta}`,
        sub: `${firstText(latest.from_week, '起始')} → ${firstText(latest.to_week, '结束')}`,
        tone: latest.coverage_delta != null && Number(latest.coverage_delta) >= 0.5 ? 'ok' : 'warn',
      },
      {
        key: 'pytest',
        label: 'pytest 通过数',
        value: latest.passed_delta == null ? '—' : `${latest.passed_delta}`,
        sub: `历史 ${metrics.history_count ?? 0}`,
        tone: latest.passed_delta != null && Number(latest.passed_delta) >= 0 ? 'ok' : 'warn',
      },
      {
        key: 'debt',
        label: '类型债务变化',
        value: latest.debt_delta == null ? '—' : `${latest.debt_delta}`,
        sub: firstText(metrics.metrics_path, 'evolution_metrics.jsonl'),
        tone: latest.debt_delta != null && Number(latest.debt_delta) <= -5 ? 'ok' : 'warn',
      },
    ]
  })

  const openApprovalItems = computed(() =>
    state.openItems
      .map((item) => asRecord(item))
      .filter((item) => firstText(item.kind, item.reason, item.run_id))
      .slice(-5)
      .reverse(),
  )

  const runTimeline = computed(() => {
    const timelines = asArray(state.raw?.run_timelines).map((item) => asRecord(item))
    const open = timelines.find((item) => item.open === true)
    const picked = open || timelines[timelines.length - 1]
    if (!picked) return null
    const items = asArray(picked.items).map((item) => asRecord(item))
    const md = state.mergeDecision
    if (md.action || md.reason) {
      items.push({
        phase: 'policy',
        step: 'risk_gate',
        label: '风险检查',
        status: firstText(md.action, md.reason),
        reason: firstText(md.reason),
        qa_verdict: firstText(md.qa_verdict),
        review_max_severity: firstText(md.review_max_severity),
      })
    }
    return {
      runId: firstText(picked.run_id),
      open: picked.open === true,
      items,
    }
  })

  return reactive({
    statusTone, statusLabel, cronLine, signalCount, threshold, riskScore, qaVerdict,
    evidenceCards, decisionCards, loopStages, kbCards, kbHitLines, kbFixHitDetails,
    kbPatternHitDetails, proactiveSignals, proactiveCandidates, proactiveCards,
    metricWindows, rosterCoverage, rosterGate, rosterRemediation, rosterAlignmentCards,
    evolutionMetricCards, openApprovalItems, runTimeline,
  })
}

export type SelfEvolutionRuntimePresenters = ReturnType<typeof useSelfEvolutionRuntimePresenters>