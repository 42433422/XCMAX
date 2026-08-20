import { computed } from 'vue'
import { loopArray, loopFirstText, loopNumber, loopRecord, loopString, type LoopRuntimeConsoleDeps } from './loopRuntimeValues'
import type { LoopRuntimeCore } from './useLoopRuntimeCore'
import type { LoopRuntimeActivity } from './useLoopRuntimeActivity'

export function useLoopRuntimePresentation(core: LoopRuntimeCore, activity: LoopRuntimeActivity, deps: LoopRuntimeConsoleDeps) {
  const { plannedIds: ALL_PLANNED_YUANGON_PKG_IDS, totalCount } = deps
  const {
    loopRuntimeSchemaVersion,
    loopRuntimeContractOk,
    loopRuntime,
    loopRuntimeContractMissingFields,
    loopRuntimeSurfaceMissing,
    loopRuntimeContractValidation,
    loopRuntimeContractRequiredFields,
    loopRuntimeContract,
    loopRuntimeSurfaceReadinessOk,
    loopRuntimeSurfaceReadiness,
    loopRuntimeSurfaceIncidents,
    loopRuntimeSurfaceIncident,
    loopRuntimeSurfaceIncidentSummary,
    loopRuntimeContractMissingNested,
    loopGovernanceAuditSummary,
    loopAlignedPlannedCount,
    loopAlignedInRosterCount,
    loopAlignedInDeployedCount,
    loopNotDeployedCount,
    loopRosterAlignment,
    loopRosterGate,
    loopOutOfRosterCount,
    loopOutOfRosterParticipantIds,
    loopRosterRemediation,
    loopParticipantIds,
    loopOpenRunCount,
    loopGateReasonText,
    loopEmployeeSpaceBridge,
    loopUiBridge,
    loopGovernanceAction,
    loopParticipantDisplay,
  } = core
  const { loopTimelineItems } = activity
  const loopRuntimeTruthCards = computed(() => [
    {
      key: 'contract',
      label: 'Runtime contract',
      value: loopFirstText(loopRuntimeSchemaVersion.value, '未知'),
      sub: loopFirstText(loopRecord(loopRecord(loopRuntime.value).source).name, 'schema/source missing'),
      tone: loopRuntimeContractOk.value ? 'ok' : 'bad',
    },
    {
      key: 'contract-fields',
      label: 'Contract fields',
      value:
        loopRuntimeContractMissingFields.value.length || loopRuntimeSurfaceMissing.value.length
          ? `missing ${loopRuntimeContractMissingFields.value.length + loopRuntimeSurfaceMissing.value.length}`
          : `${loopNumber(loopRuntimeContractValidation.value.required_count) ?? loopRuntimeContractRequiredFields.value.length}`,
      sub: loopRuntimeContractMissingFields.value.length
        ? `缺字段=${loopRuntimeContractMissingFields.value.slice(0, 4).join(' / ')}`
        : loopRuntimeSurfaceMissing.value.length
          ? `本页缺依赖=${loopRuntimeSurfaceMissing.value.slice(0, 4).join(' / ')}`
          : loopArray(loopRuntimeContract.value.surfaces).length
            ? `surfaces=${loopArray(loopRuntimeContract.value.surfaces)
                .map((item) => loopString(item))
                .filter(Boolean)
                .join(' / ')}`
            : 'contract.required_top_level/surfaces missing',
      tone: loopRuntimeContractOk.value ? 'ok' : 'warn',
    },
    {
      key: 'surface-ready',
      label: 'Employee surface',
      value: loopRuntimeSurfaceReadinessOk.value ? '就绪' : '异常',
      sub: loopRuntimeSurfaceMissing.value.length
        ? `${loopFirstText(loopRuntimeSurfaceReadiness.value.action, 'repair')} · ${loopRuntimeSurfaceMissing.value.slice(0, 3).join(' / ')}`
        : loopFirstText(
            loopRuntimeSurfaceReadiness.value.title,
            `required=${loopArray(loopRuntimeSurfaceReadiness.value.required).length || 0}`,
          ),
      tone: loopRuntimeSurfaceReadinessOk.value ? 'ok' : 'bad',
    },
    {
      key: 'surface-incident',
      label: 'Surface incident',
      value: loopRuntimeSurfaceIncidents.value.length ? `${loopRuntimeSurfaceIncidents.value.length}` : 'none',
      sub: loopRuntimeSurfaceIncidents.value.length
        ? loopFirstText(loopRuntimeSurfaceIncident.value.action, loopRuntimeSurfaceIncident.value.title, 'inspect_runtime_contract')
        : 'employee_space 当前没有 contract incident',
      tone: loopRuntimeSurfaceIncidents.value.length ? 'bad' : 'ok',
    },
    {
      key: 'incident-summary',
      label: 'Incident summary',
      value: loopFirstText(
        loopRuntimeSurfaceIncidentSummary.value.status,
        `${loopNumber(loopRuntimeSurfaceIncidentSummary.value.total) ?? 0}`,
      ),
      sub: loopFirstText(loopRuntimeSurfaceIncidentSummary.value.primary_action)
        ? `${loopRuntimeSurfaceIncidentSummary.value.primary_action} -> ${loopFirstText(loopRuntimeSurfaceIncidentSummary.value.primary_target_surface, loopRuntimeSurfaceIncidentSummary.value.primary_surface, '未知')} · 总计 ${loopNumber(loopRuntimeSurfaceIncidentSummary.value.total) ?? 0}`
        : loopArray(loopRuntimeSurfaceIncidentSummary.value.surfaces).length
          ? `surfaces=${loopArray(loopRuntimeSurfaceIncidentSummary.value.surfaces)
              .map((item) => loopString(item))
              .filter(Boolean)
              .join(' / ')}`
          : '全局 surface incident clear',
      tone: loopNumber(loopRuntimeSurfaceIncidentSummary.value.total) ? 'warn' : 'ok',
    },
    {
      key: 'global-nested',
      label: 'Global nested audit',
      value: loopRuntimeContractMissingNested.value.length ? `missing ${loopRuntimeContractMissingNested.value.length}` : 'clear',
      sub: loopRuntimeContractMissingNested.value.length
        ? loopRuntimeContractMissingNested.value.slice(0, 4).join(' / ')
        : `全局=${loopRuntimeContractValidation.value.global_ok === false ? '异常' : '正常'} · 所有模块=${loopRuntimeContractValidation.value.all_surfaces_ok === false ? '异常' : '正常'}`,
      tone: loopRuntimeContractMissingNested.value.length ? 'warn' : 'ok',
    },
    {
      key: 'runtime',
      label: 'Runtime source',
      value: loopRuntime.value ? 'connected' : 'missing',
      sub: loopRuntime.value ? '来自 selfMaintenanceRuntimeStatus 实时接口' : '未拿到后端 runtime，当前页面不能证明 loop 已运行',
      tone: loopRuntime.value ? 'ok' : 'bad',
    },
    {
      key: 'ledger',
      label: 'Ledger evidence',
      value: loopTimelineItems.value.length ? `${loopTimelineItems.value.length}` : 'no events',
      sub: loopTimelineItems.value.length ? 'run_timelines 已回写员工 step' : '没有 timeline 事件，不伪造成员工执行',
      tone: loopTimelineItems.value.length ? 'run' : 'warn',
    },
    {
      key: 'participants',
      label: 'Employee binding',
      value: loopParticipantIds.value.length ? `${loopParticipantIds.value.length}` : 'none',
      sub: loopParticipantIds.value.length ? '已从 participants / ledger 绑定到上岗员工' : '没有 employee_id/actor 绑定',
      tone: loopParticipantIds.value.length ? 'run' : 'warn',
    },
    {
      key: 'governance',
      label: 'Governance audit',
      value: loopGovernanceAuditSummary.value.recent_count != null ? `${loopGovernanceAuditSummary.value.recent_count}` : 'no audit',
      sub:
        loopGovernanceAuditSummary.value.recent_count != null
          ? `health=${loopGovernanceAuditSummary.value.health || 'ok'}`
          : '没有治理审计记录，不隐藏风险',
      tone: loopGovernanceAuditSummary.value.health === 'bad' ? 'bad' : 'ok',
    },
  ])

  const loopRuntimeFreshnessCards = computed(() => {
    const payload = loopRecord(loopRuntime.value)
    const generatedAt = loopFirstText(payload.generated_at, payload.created_at, payload.snapshot_at)
    const updatedAt = loopFirstText(payload.updated_at, payload.refreshed_at, payload.last_seen_at, payload.last_run_at)
    const ledgerAt = loopFirstText(
      loopTimelineItems.value[loopTimelineItems.value.length - 1]?.at,
      payload.latest_event_at,
      payload.latest_run_at,
    )
    return [
      {
        key: 'snapshot',
        label: 'Snapshot time',
        value: generatedAt || 'timestamp missing',
        sub: generatedAt ? '后端 runtime 快照时间' : '后端没有返回快照时间，不伪装实时',
        tone: generatedAt ? 'ok' : 'warn',
      },
      {
        key: 'refresh',
        label: 'Runtime update',
        value: updatedAt || '未知',
        sub: updatedAt ? '后端声明的最近更新时间' : '未拿到 updated/refreshed/last_seen 字段',
        tone: updatedAt ? 'ok' : 'warn',
      },
      {
        key: 'ledger',
        label: 'Latest ledger event',
        value: ledgerAt || 'no event time',
        sub: ledgerAt ? '最近一条 timeline 事件时间' : 'ledger 事件没有时间戳或没有事件',
        tone: ledgerAt ? 'run' : 'warn',
      },
    ]
  })

  const loopIsolationCards = computed(() => [
    {
      key: 'roster',
      label: '编制基线',
      value: `${loopAlignedPlannedCount.value}`,
      sub: '以编制图谱为准，不把商店员工混入工位',
      tone: 'ok',
    },
    {
      key: 'workspace',
      label: '员工空间',
      value: `${totalCount.value}`,
      sub: '只展示企业 Mod 栈内上岗工位',
      tone: totalCount.value > 0 ? 'run' : 'warn',
    },
    {
      key: 'loop',
      label: 'Loop 调度',
      value: `${loopAlignedInDeployedCount.value}`,
      sub: `编制命中 ${loopAlignedInRosterCount.value} · 已上岗命中`,
      tone: loopAlignedInDeployedCount.value > 0 ? 'run' : 'warn',
    },
    {
      key: 'not-deployed',
      label: '未登记上岗',
      value: `${loopNotDeployedCount.value}`,
      sub: loopNotDeployedCount.value
        ? loopArray(loopRosterAlignment.value.not_deployed_ids)
            .map((id) => loopString(id))
            .filter(Boolean)
            .slice(0, 3)
            .join(' / ') || loopFirstText(loopRosterGate.value.reason, '编制内但未登记上岗')
        : '参与者均已登记上岗',
      tone: loopNotDeployedCount.value ? 'bad' : 'ok',
    },
    {
      key: 'blocked',
      label: '隔离拦截',
      value: `${loopOutOfRosterCount.value}`,
      sub: loopOutOfRosterCount.value
        ? loopOutOfRosterParticipantIds.value.slice(0, 3).join(' / ') ||
          loopFirstText(loopRosterGate.value.reason, '非编制参与者已由后端隔离')
        : loopFirstText(loopRosterGate.value.action, '未发现非编制参与者'),
      tone: loopOutOfRosterCount.value ? 'bad' : 'ok',
    },
  ])

  const loopDiagnosis = computed(() => {
    if (!loopRuntime.value) {
      return {
        tone: 'warn',
        title: 'Loop runtime 未连接',
        detail: '员工空间还没有拿到 self-maintenance runtime 状态，先检查 MODstore 后端和 market proxy。',
        actions: ['确认后端进程存活', '确认 /ops/self-maintenance/status 可访问'],
      }
    }
    if (!loopRuntimeContractOk.value) {
      const missingText = loopRuntimeContractMissingFields.value.length
        ? ` 缺字段：${loopRuntimeContractMissingFields.value.slice(0, 5).join(' / ')}。`
        : loopRuntimeSurfaceMissing.value.length
          ? ` 当前 surface 缺依赖：${loopRuntimeSurfaceMissing.value.slice(0, 5).join(' / ')}。`
          : ''
      return {
        tone: 'bad',
        title: loopFirstText(loopRuntimeSurfaceReadiness.value.title, 'Loop runtime contract 不匹配'),
        detail: `${loopRuntimeSurfaceReadiness.value.detail || `当前版本=${loopRuntimeSchemaVersion.value || '未知'}，员工空间只认 self_maintenance_runtime v1，避免旧接口被误判。`}${missingText}`,
        actions: [loopFirstText(loopRuntimeSurfaceReadiness.value.action, '检查后端 runtime status contract'), '回编制图谱查看治理待办'],
      }
    }
    if (loopRosterGate.value.action === 'hold' || loopNotDeployedCount.value) {
      const targets = loopArray(loopRosterRemediation.value.target_employee_ids)
        .map((id) => loopString(id))
        .filter(Boolean)
      return {
        tone: 'bad',
        title: loopFirstText(loopRosterRemediation.value.title, '编制员工未登记上岗'),
        detail: `${loopFirstText(loopRosterRemediation.value.detail, '编制内但未登记上岗，需要补登记后才允许自维护自动放行。')}${targets.length ? ` 目标：${targets.slice(0, 4).join(' / ')}` : ''}`,
        actions: [loopFirstText(loopRosterRemediation.value.action, 'register_duty_employees'), '确认上岗员工和商店员工隔离'],
      }
    }
    if (loopRosterGate.value.blocking === true || loopOutOfRosterCount.value) {
      const targets = loopArray(loopRosterRemediation.value.target_employee_ids)
        .map((id) => loopString(id))
        .filter(Boolean)
      return {
        tone: 'bad',
        title: loopFirstText(loopRosterRemediation.value.title, '发现非编制参与者'),
        detail: `${loopFirstText(loopRosterRemediation.value.detail, `后端 gate=${loopFirstText(loopRosterGate.value.action, 'isolate')}，原因：${loopFirstText(loopRosterGate.value.reason, 'out_of_roster_participants_detected')}。`)}${targets.length ? ` 目标：${targets.slice(0, 4).join(' / ')}` : ''}`,
        actions: [loopFirstText(loopRosterRemediation.value.action, 'isolate_out_of_roster_participants'), '按 gate 策略隔离非编制员工'],
      }
    }
    if (!loopParticipantIds.value.length) {
      return {
        tone: 'warn',
        title: '本轮未看到编制员工参与',
        detail: 'runtime 可能还没有打开 run，也可能 ledger 缺少 employee_id/actor 回写。',
        actions: ['等待缺证阈值触发', '检查 ledger 是否写 employee_id'],
      }
    }
    if (loopOpenRunCount.value > 0) {
      return {
        tone: 'run',
        title: '上岗员工正在参与自维护',
        detail: `${loopParticipantIds.value.length} 个编制员工参与，${loopOpenRunCount.value} 个 run 尚未闭环。`,
        actions: ['查看下方工位高亮', '进入完整 Loop 时间线'],
      }
    }
    return {
      tone: 'ok',
      title: 'Loop 边界正常',
      detail: `当前参与者都命中编制基线，门禁状态：${loopGateReasonText.value || '待命'}。`,
      actions: ['继续观察 30 秒轮询', '必要时手动刷新状态'],
    }
  })

  const loopGovernanceBridge = computed(() => {
    const bridgeTitle = loopFirstText(loopEmployeeSpaceBridge.value.title, loopUiBridge.value.title)
    if (loopRuntime.value && bridgeTitle) {
      return {
        tone: loopFirstText(loopUiBridge.value.tone, 'ok'),
        label: loopFirstText(loopEmployeeSpaceBridge.value.role, loopUiBridge.value.primary_surface, '执行面'),
        title: bridgeTitle,
        detail: loopFirstText(loopEmployeeSpaceBridge.value.detail, loopUiBridge.value.detail),
        cta: loopFirstText(loopEmployeeSpaceBridge.value.cta, '查看治理面'),
        actionLabel: loopFirstText(loopGovernanceAction.value.label, loopUiBridge.value.primary_action, '观察 Loop'),
        actionStatus: loopFirstText(loopGovernanceAction.value.status, 'informational'),
        actionExecutable: loopGovernanceAction.value.executable !== false,
        actionRequiresAdmin: loopGovernanceAction.value.requires_admin === true,
      }
    }
    if (!loopRuntime.value) {
      return {
        tone: 'warn',
        label: '管控面',
        title: '去编制图谱接入 runtime',
        detail: '员工空间只展示工位和执行态；后端 runtime、gate、补登记动作统一在编制图谱处理。',
        cta: '打开编制图谱',
        actionLabel: '连接 runtime',
        actionStatus: 'requires_check',
        actionExecutable: false,
        actionRequiresAdmin: false,
      }
    }
    if (loopRosterGate.value.action === 'hold' || loopNotDeployedCount.value) {
      const targets = loopArray(loopRosterRemediation.value.target_employee_ids)
        .map((id) => loopString(id))
        .filter(Boolean)
      return {
        tone: 'bad',
        label: '上岗治理',
        title: '需要在编制图谱补登记',
        detail: targets.length
          ? `待补登记：${targets.slice(0, 5).join(' / ')}。员工空间不直接改编制，避免工位页绕过上岗门禁。`
          : 'Loop gate 已进入 hold，需要回编制图谱执行上岗登记后再放行自维护。',
        cta: '去补登记',
        actionLabel: '补登记上岗员工',
        actionStatus: 'requires_action',
        actionExecutable: true,
        actionRequiresAdmin: true,
      }
    }
    if (loopRosterGate.value.blocking === true || loopOutOfRosterCount.value) {
      return {
        tone: 'bad',
        label: '隔离治理',
        title: '非编制员工必须在图谱隔离',
        detail: '员工空间只展示企业 Mod 栈工位；非编制/商店员工的隔离策略由编制图谱统一执行。',
        cta: '查看隔离',
        actionLabel: '隔离非编制参与者',
        actionStatus: 'enforced',
        actionExecutable: false,
        actionRequiresAdmin: true,
      }
    }
    if (loopParticipantIds.value.length) {
      return {
        tone: loopOpenRunCount.value > 0 ? 'run' : 'ok',
        label: '执行面',
        title: '员工空间展示真实工作现场',
        detail: '当前页负责看哪些上岗员工参与 Loop；编制图谱负责治理和准入，完整 Loop 负责时间线。',
        cta: '看治理面',
        actionLabel: '观察 Loop 状态',
        actionStatus: loopOpenRunCount.value > 0 ? '运行中' : '就绪',
        actionExecutable: false,
        actionRequiresAdmin: false,
      }
    }
    return {
      tone: 'warn',
      label: '等待派发',
      title: 'Loop 尚未把任务落到工位',
      detail: '先等缺证阈值或 incident 触发；触发后这里会高亮真实上岗员工，编制图谱会显示治理结论。',
      cta: '看门禁',
      actionLabel: '等待派发',
      actionStatus: 'waiting',
      actionExecutable: false,
      actionRequiresAdmin: false,
    }
  })

  function loopRoleGroupKey(row: Record<string, unknown>): 'scout' | 'fix' | 'review' | 'qa' | 'verify' | 'ops' | 'other' {
    const text = [row.role, row.role_label, row.stage, row.stage_label, ...loopArray(row.stages), ...loopArray(row.stage_labels)]
      .map((x) => loopString(x).toLowerCase())
      .join(' ')
    if (/scout|侦察|intake|dispatch|router|感知/.test(text)) return 'scout'
    if (/fix|repair|coding|修复|编码/.test(text)) return 'fix'
    if (/review|validator|评审|审查/.test(text)) return 'review'
    if (/qa|test|sandbox|测试|质检/.test(text)) return 'qa'
    if (/verify|self-check|验证|自检/.test(text)) return 'verify'
    if (/ops|host|运维|恢复/.test(text)) return 'ops'
    return 'other'
  }

  const loopRoleGroups = computed(() => {
    const meta: Record<string, { label: string; workers: string[] }> = {
      scout: { label: '侦察 / 派发', workers: [] },
      fix: { label: '修复 / 编码', workers: [] },
      review: { label: '评审 / 风险', workers: [] },
      qa: { label: 'QA / 沙箱', workers: [] },
      verify: { label: '验证 / 自检', workers: [] },
      ops: { label: '运维 / 宿主', workers: [] },
      other: { label: '其他参与', workers: [] },
    }
    const seen = new Set<string>()
    const payload = loopRuntime.value || {}
    for (const item of loopArray(loopRecord(payload).participants)) {
      const row = loopRecord(item)
      const id = loopString(row.employee_id || row.id)
      if (!id || !ALL_PLANNED_YUANGON_PKG_IDS.value.has(id)) continue
      meta[loopRoleGroupKey(row)].workers.push(loopParticipantDisplay(id))
      seen.add(id)
    }
    for (const id of loopParticipantIds.value) {
      if (!seen.has(id)) meta.other.workers.push(loopParticipantDisplay(id))
    }
    return Object.entries(meta)
      .map(([key, value]) => ({ key, ...value }))
      .filter((group) => group.workers.length > 0)
  })
  return {
    loopRuntimeTruthCards,
    loopRuntimeFreshnessCards,
    loopIsolationCards,
    loopDiagnosis,
    loopGovernanceBridge,
    loopRoleGroups,
  }
}

export type LoopRuntimePresentation = ReturnType<typeof useLoopRuntimePresentation>
