/**
 * 自进化 loop 运行时数据（由 SelfEvolutionLoopRuntimePanel.vue 原文机械切分而来，行为保持不变）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'
import { asArray, asNumber, asRecord, asString, firstText, type AnyRecord } from './runtimeHelpers'
import { useRuntimeParticipants } from './useRuntimeParticipants'

export interface SelfEvolutionRuntimeProps {
  compact: boolean
  surface: 'employee-space' | 'duty-roster'
}

/** KB 命中明细：模板读取嵌套 ``executable_template.rollback_plan``，其余字段保持开放。 */
export interface KbHitDetail {
  [key: string]: unknown
  executable_template?: { rollback_plan?: unknown } | null
}

export function useSelfEvolutionRuntime(props: SelfEvolutionRuntimeProps) {
  const raw = ref<AnyRecord | null>(null)
  const loading = ref(false)
  const error = ref('')
  const paraCopied = ref(false)
  let timer: number | null = null

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      raw.value = await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(props.compact ? 40 : 80) as AnyRecord
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    void refresh()
    timer = window.setInterval(() => {
      void refresh()
    }, 30000)
  })

  onBeforeUnmount(() => {
    if (timer != null) window.clearInterval(timer)
    timer = null
  })

  const evidence = computed<AnyRecord>(() => asRecord(raw.value?.evidence))
  const memory = computed<AnyRecord>(() => asRecord(raw.value?.memory))
  const policy = computed<AnyRecord>(() => asRecord(raw.value?.policy))
  const gate = computed<AnyRecord>(() => asRecord(raw.value?.current_gate))
  const cron = computed<AnyRecord>(() => asRecord(raw.value?.cron))
  const kbSummary = computed<AnyRecord>(() => asRecord(raw.value?.kb_summary))
  const evolutionMetrics = computed<AnyRecord>(() => asRecord(raw.value?.evolution_metrics_summary))
  const rosterAlignment = computed<AnyRecord>(() => asRecord(raw.value?.roster_alignment))
  const currentGovernanceGate = computed<AnyRecord>(() => asRecord(raw.value?.governance_gate))
  const uiBridge = computed<AnyRecord>(() => asRecord(raw.value?.ui_bridge))
  const governanceAudit = computed<AnyRecord>(() => asRecord(raw.value?.governance_audit))
  const governanceAuditSummary = computed<AnyRecord>(() => asRecord(governanceAudit.value.summary))
  const governanceAuditLast = computed<AnyRecord>(() => asRecord(governanceAudit.value.last))
  const governanceAuditRecent = computed(() =>
    asArray(governanceAudit.value.recent)
      .map((item) => asRecord(item))
      .filter((item) => firstText(item.action, item.created_at)),
  )

  const latestComplete = computed<AnyRecord>(() => asRecord(evidence.value.latest_complete))
  const latestSkip = computed<AnyRecord>(() => asRecord(evidence.value.latest_skip))
  const lastRun = computed<AnyRecord>(() => {
    const fromMemory = asRecord(memory.value.last_run)
    if (Object.keys(fromMemory).length) return fromMemory
    if (Object.keys(latestComplete.value).length) return latestComplete.value
    return latestSkip.value
  })
  const decision = computed<AnyRecord>(() => asRecord(memory.value.last_policy_decision))
  const mergeDecision = computed<AnyRecord>(() => {
    const structured = asRecord(raw.value?.merge_decision)
    if (Object.keys(structured).length) return structured
    return {
      action: firstText(decision.value.action),
      reason: firstText(decision.value.reason),
      risk_score_v1: asRecord(decision.value.risk_score),
      safety_score_v2: asRecord(decision.value.safety_score_v2),
      safety_score_v3: asRecord(decision.value.safety_score_v3),
      roster_gate: asRecord(decision.value.roster_gate),
      qa_verdict: firstText(asRecord(decision.value.qa).verdict),
      review_max_severity: firstText(asRecord(decision.value.review).max_severity),
    }
  })
  const openRunIds = computed(() => asArray(evidence.value.open_run_ids).map((x) => asString(x)).filter(Boolean))
  const openItems = computed(() => asArray(memory.value.open_items))
  const recentRuns = computed(() => asArray(memory.value.recent_runs))

  const { teamLanes } = useRuntimeParticipants({ raw, evidence, memory })

  const runTimeline = computed(() => {
    const timelines = asArray(raw.value?.run_timelines).map((item) => asRecord(item))
    const open = timelines.find((item) => item.open === true)
    const picked = open || timelines[timelines.length - 1]
    if (!picked) return null
    const items = asArray(picked.items).map((item) => asRecord(item))
    const md = mergeDecision.value
    if (md.action || md.reason) {
      items.push({
        phase: 'policy',
        step: 'risk_gate',
        label: 'Risk / Merge Gate',
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

  const statusTone = computed(() => {
    if (error.value) return 'bad'
    if (openRunIds.value.length > 0) return 'running'
    if (gate.value.should_run === true) return 'warn'
    if (asString(latestComplete.value.phase) === 'complete') return 'ok'
    return 'idle'
  })

  const statusLabel = computed(() => {
    if (error.value) return '接口异常'
    if (openRunIds.value.length > 0) return '运行中'
    if (gate.value.should_run === true) return '达到触发阈值'
    if (asString(gate.value.reason) === 'cooldown') return '冷却中'
    if (asString(latestComplete.value.phase) === 'complete') return '最近完成'
    return '待命'
  })

  const cronLine = computed(() => {
    const hour = asNumber(cron.value.hour, 3)
    const minute = asNumber(cron.value.minute, 0)
    const tz = firstText(cron.value.timezone, 'Asia/Shanghai')
    return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${tz}`
  })

  const decisionCards = computed(() => {
    const md = mergeDecision.value
    const cards = [
      {
        key: 'action',
        label: 'Action',
        value: firstText(md.action, '等待决策'),
        sub: firstText(md.reason, 'policy pending'),
      },
    ]
    const v1 = asRecord(md.risk_score_v1)
    const v2 = asRecord(md.safety_score_v2)
    const v3 = asRecord(md.safety_score_v3)
    const roster = asRecord(md.roster_gate)
    const governance = Object.keys(asRecord(md.governance_gate)).length
      ? asRecord(md.governance_gate)
      : currentGovernanceGate.value
    const evolution = asRecord(md.evolution_gate)
    if (v1.score != null) cards.push({
      key: 'v1',
      label: 'V1 风险分',
      value: String(v1.score),
      sub: `max ${v1.max_allowed ?? '—'} · ${firstText(v1.reason, v1.source, '')}`,
    })
    if (v2.score != null) cards.push({
      key: 'v2',
      label: 'V2 安全分',
      value: String(v2.score),
      sub: `min ${v2.min_allowed ?? '—'} · ${firstText(v2.reason, v2.source, '')}`,
    })
    if (v3.score != null) cards.push({
      key: 'v3',
      label: 'V3 安全分',
      value: String(v3.score),
      sub: `min ${v3.min_allowed ?? '—'} · ${firstText(v3.reason, v3.source, '')}`,
    })
    if (md.qa_verdict || md.review_max_severity) cards.push({
      key: 'qa',
      label: 'QA / Review',
      value: firstText(md.qa_verdict, '—'),
      sub: md.review_max_severity ? `review ${md.review_max_severity}` : 'structured gate',
    })
    if (Object.keys(roster).length) cards.push({
      key: 'roster',
      label: 'Roster Gate',
      value: firstText(roster.action, roster.ok === true ? 'allow' : 'blocked'),
      sub: firstText(roster.reason, roster.policy, 'roster policy'),
    })
    if (Object.keys(governance).length) cards.push({
      key: 'governance',
      label: 'Governance Gate',
      value: firstText(governance.action, governance.ok === true ? 'allow' : 'blocked'),
      sub: firstText(
        governance.reason,
        asRecord(governance.summary).health,
        governance.policy,
        'governance audit policy',
      ),
    })
    if (Object.keys(evolution).length) cards.push({
      key: 'evolution',
      label: 'Evolution Gate',
      value: evolution.pause === true ? 'pause' : 'allow',
      sub: firstText(evolution.reason, `history ${evolution.history_count ?? 0}`, 'evolution metrics policy'),
    })
    return cards
  })

  const kbCards = computed(() => {
    const kb = kbSummary.value
    const redis = asRecord(kb.redisvl_status)
    return [
      {
        key: 'redisvl',
        label: 'RedisVL',
        value: redis.ready === true ? 'ready' : 'not ready',
        sub: firstText(redis.reason, redis.error, redis.backend, 'vector index'),
        tone: redis.ready === true ? 'ok' : 'warn',
      },
      {
        key: 'fix',
        label: '修复知识命中',
        value: String(asNumber(kb.fix_hit_count, 0)),
        sub: firstText(kb.engine, 'KB search'),
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
    const fixes = asArray(kbSummary.value.top_fix_hits).map((item) => {
      const row = asRecord(item)
      return firstText(row.symptom, row.root_cause, row.path)
    }).filter(Boolean)
    const patterns = asArray(kbSummary.value.top_pattern_hits).map((item) => {
      const row = asRecord(item)
      return firstText(row.pattern, row.summary, row.path)
    }).filter(Boolean)
    return [...fixes, ...patterns].slice(0, 5)
  })

  const kbFixHitDetails = computed(() =>
    asArray(kbSummary.value.top_fix_hits).map((item) => asRecord(item) as KbHitDetail).slice(0, 3),
  )

  const kbPatternHitDetails = computed(() =>
    asArray(kbSummary.value.top_pattern_hits).map((item) => asRecord(item) as KbHitDetail).slice(0, 3),
  )

  const proactiveSignals = computed<AnyRecord>(() => asRecord(gate.value.proactive_signals))
  const proactiveCandidates = computed(() =>
    asArray(proactiveSignals.value.candidates)
      .map((item) => asRecord(item))
      .slice(0, 6),
  )

  const proactiveCards = computed(() => {
    const count = asNumber(gate.value.proactive_task_count, proactiveCandidates.value.length)
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
        sub: Array.from(kinds).slice(0, 3).join(' / ') || 'performance / coverage / debt',
        tone: kinds.size > 0 ? 'ok' : 'idle',
      },
      {
        key: 'source',
        label: '信号源',
        value: firstText(proactiveSignals.value.source, proactiveSignals.value.engine, 'scripts/dev'),
        sub: firstText(proactiveSignals.value.generated_at, proactiveSignals.value.checked_at, 'runtime scan'),
        tone: 'idle',
      },
    ]
  })

  const metricWindows = computed(() =>
    asArray(evolutionMetrics.value.windows).map((item) => asRecord(item)).slice(-2),
  )

  const rosterCoverage = computed(() =>
    asArray(rosterAlignment.value.department_coverage)
      .map((item) => asRecord(item))
      .filter((item) => String(item.key || item.label || '').trim()),
  )

  const rosterGate = computed<AnyRecord>(() => asRecord(rosterAlignment.value.gate))
  const rosterRemediation = computed<AnyRecord>(() => asRecord(rosterAlignment.value.remediation))

  const rosterAlignmentCards = computed(() => [
    {
      key: 'planned',
      label: '编制基线',
      value: `${rosterAlignment.value.planned_count ?? '—'}`,
      sub: firstText(rosterAlignment.value.source, 'duty_roster.py'),
      tone: 'ok',
    },
    {
      key: 'participants',
      label: 'Loop 编制命中',
      value: `${rosterAlignment.value.in_roster_count ?? '—'}`,
      sub: `runtime participants ${rosterAlignment.value.participant_count ?? 0}`,
      tone: Number(rosterAlignment.value.in_roster_count || 0) > 0 ? 'run' : 'warn',
    },
    {
      key: 'deployed',
      label: 'Loop 上岗命中',
      value: `${rosterAlignment.value.in_deployed_count ?? '—'}`,
      sub: `registered duty ${rosterAlignment.value.deployed_count ?? 0}`,
      tone: Number(rosterAlignment.value.in_deployed_count || 0) > 0 ? 'run' : 'warn',
    },
    {
      key: 'outside',
      label: '非编制混入',
      value: `${rosterAlignment.value.out_of_roster_count ?? 0}`,
      sub: asArray(rosterAlignment.value.out_of_roster_ids).map((id) => String(id)).filter(Boolean).slice(0, 3).join(' / ') || '未混入',
      tone: Number(rosterAlignment.value.out_of_roster_count || 0) > 0 ? 'bad' : 'ok',
    },
    {
      key: 'not-deployed',
      label: '未登记上岗',
      value: `${rosterAlignment.value.not_deployed_count ?? 0}`,
      sub: asArray(rosterAlignment.value.not_deployed_ids).map((id) => String(id)).filter(Boolean).slice(0, 3).join(' / ') || '全部已登记',
      tone: Number(rosterAlignment.value.not_deployed_count || 0) > 0 ? 'bad' : 'ok',
    },
    {
      key: 'coverage',
      label: '部门覆盖',
      value: `${rosterCoverage.value.length}`,
      sub: firstText(rosterAlignment.value.status, 'roster alignment'),
      tone: rosterCoverage.value.length > 0 ? 'run' : 'warn',
    },
    {
      key: 'gate',
      label: '隔离策略',
      value: firstText(rosterGate.value.action, '—'),
      sub: firstText(rosterGate.value.reason, rosterGate.value.policy, 'roster gate'),
      tone: rosterGate.value.blocking === true ? 'bad' : rosterGate.value.action === 'allow' ? 'ok' : 'warn',
    },
  ])

  const evolutionMetricCards = computed(() => {
    const latest = metricWindows.value[metricWindows.value.length - 1] || {}
    return [
      {
        key: 'pause',
        label: '自进化状态',
        value: evolutionMetrics.value.pause === true ? '暂停' : '允许运行',
        sub: firstText(evolutionMetrics.value.reason, 'metrics gate'),
        tone: evolutionMetrics.value.pause === true ? 'bad' : 'ok',
      },
      {
        key: 'coverage',
        label: '覆盖率变化',
        value: latest.coverage_delta == null ? '—' : `${latest.coverage_delta}`,
        sub: `${firstText(latest.from_week, 'from')} → ${firstText(latest.to_week, 'to')}`,
        tone: latest.coverage_delta != null && Number(latest.coverage_delta) >= 0.5 ? 'ok' : 'warn',
      },
      {
        key: 'pytest',
        label: 'pytest 通过数',
        value: latest.passed_delta == null ? '—' : `${latest.passed_delta}`,
        sub: `history ${evolutionMetrics.value.history_count ?? 0}`,
        tone: latest.passed_delta != null && Number(latest.passed_delta) >= 0 ? 'ok' : 'warn',
      },
      {
        key: 'debt',
        label: '类型债务变化',
        value: latest.debt_delta == null ? '—' : `${latest.debt_delta}`,
        sub: firstText(evolutionMetrics.value.metrics_path, 'evolution_metrics.jsonl'),
        tone: latest.debt_delta != null && Number(latest.debt_delta) <= -5 ? 'ok' : 'warn',
      },
    ]
  })

  const signalCount = computed(() => asNumber(gate.value.signal_count, 0))
  const threshold = computed(() => asNumber(gate.value.threshold, asNumber(policy.value.threshold, 1)))
  const riskScore = computed(() => {
    const v3 = asRecord(decision.value.safety_score_v3)
    const v2 = asRecord(decision.value.safety_score_v2)
    const v1 = asRecord(decision.value.risk_score)
    if (v3.score != null) return { label: 'V3 安全分', value: asNumber(v3.score) }
    if (v2.score != null) return { label: 'V2 安全分', value: asNumber(v2.score) }
    if (v1.score != null) return { label: 'V1 风险分', value: asNumber(v1.score) }
    return null
  })

  const qaVerdict = computed(() => {
    const qa = asRecord(decision.value.qa)
    const reviewGate = asRecord(decision.value.structured_gate)
    return firstText(qa.verdict, reviewGate.qa_verdict, lastRun.value.qa_verdict, '待回写')
  })

  const paraTaskId = computed(() =>
    firstText(
      lastRun.value.para_task_id,
      asRecord(lastRun.value.result).para_task_id,
      asRecord(decision.value.final).para_task_id,
    ),
  )

  async function copyParaTaskId() {
    const value = paraTaskId.value
    if (!value || typeof navigator === 'undefined' || !navigator.clipboard) return
    await navigator.clipboard.writeText(value)
    paraCopied.value = true
    window.setTimeout(() => {
      paraCopied.value = false
    }, 1400)
  }

  const branchName = computed(() =>
    firstText(
      lastRun.value.branch,
      lastRun.value.target_branch,
      asRecord(decision.value.final).branch,
    ),
  )

  const actionLabel = computed(() =>
    firstText(decision.value.action, lastRun.value.action, lastRun.value.status, latestSkip.value.reason, '等待决策'),
  )

  const loopStages = computed(() => [
    {
      key: 'signals',
      title: '信号感知',
      value: `${signalCount.value}/${threshold.value}`,
      meta: firstText(gate.value.reason, 'below_threshold'),
      tone: signalCount.value >= threshold.value ? 'warn' : 'idle',
    },
    {
      key: 'incident',
      title: 'Incident 入池',
      value: String(asNumber(gate.value.incident_count, 0)),
      meta: `${asNumber(gate.value.lookback_hours, 24)}h 窗口`,
      tone: asNumber(gate.value.incident_count, 0) > 0 ? 'running' : 'idle',
    },
    {
      key: 'team',
      title: '三员工执行',
      value: openRunIds.value.length ? `${openRunIds.value.length} 轮` : '待命',
      meta: 'Scout / Fix / QA',
      tone: openRunIds.value.length ? 'running' : 'idle',
    },
    {
      key: 'qa',
      title: 'QA JSON',
      value: qaVerdict.value,
      meta: '结构化门禁',
      tone: qaVerdict.value === 'PASS' ? 'ok' : qaVerdict.value === 'FAIL' ? 'bad' : 'idle',
    },
    {
      key: 'risk',
      title: 'Risk Gate',
      value: riskScore.value ? String(riskScore.value.value) : '待评分',
      meta: riskScore.value?.label || 'V1/V2/V3',
      tone: riskScore.value ? 'ok' : 'idle',
    },
    {
      key: 'merge',
      title: '合并/审批',
      value: actionLabel.value,
      meta: branchName.value || 'branch 待回写',
      tone: /merge|merged|pass|auto/i.test(actionLabel.value) ? 'ok' : 'idle',
    },
  ])

  const evidenceCards = computed(() => [
    { label: 'Para task', value: paraTaskId.value || '无进行中任务' },
    { label: 'Open items', value: String(openItems.value.length) },
    { label: 'Recent runs', value: String(recentRuns.value.length) },
    { label: 'Cooldown', value: `${asNumber(policy.value.cooldown_minutes, 360)} min` },
  ])

  const openApprovalItems = computed(() =>
    openItems.value
      .map((item) => asRecord(item))
      .filter((item) => firstText(item.kind, item.reason, item.run_id))
      .slice(-5)
      .reverse(),
  )

  return {
    raw,
    loading,
    error,
    refresh,
    paraCopied,
    paraTaskId,
    copyParaTaskId,
    evidence,
    memory,
    policy,
    gate,
    cron,
    cronLine,
    decision,
    mergeDecision,
    lastRun,
    latestComplete,
    latestSkip,
    openRunIds,
    openItems,
    recentRuns,
    teamLanes,
    runTimeline,
    statusTone,
    statusLabel,
    decisionCards,
    kbSummary,
    kbCards,
    kbHitLines,
    kbFixHitDetails,
    kbPatternHitDetails,
    proactiveSignals,
    proactiveCandidates,
    proactiveCards,
    metricWindows,
    evolutionMetrics,
    evolutionMetricCards,
    rosterAlignment,
    rosterCoverage,
    rosterGate,
    rosterRemediation,
    rosterAlignmentCards,
    signalCount,
    threshold,
    riskScore,
    qaVerdict,
    branchName,
    actionLabel,
    loopStages,
    evidenceCards,
    openApprovalItems,
    currentGovernanceGate,
    uiBridge,
    governanceAudit,
    governanceAuditSummary,
    governanceAuditLast,
    governanceAuditRecent,
  }
}
