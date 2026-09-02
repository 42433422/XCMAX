/**
 * 参与员工泳道（由 SelfEvolutionLoopRuntimePanel.vue 原文机械切分而来，行为保持不变）。
 */
import type { ComputedRef, Ref } from 'vue'
import { computed } from 'vue'
import { asArray, asRecord, asString, firstText, type AnyRecord } from './runtimeHelpers'

export type SelfEvolutionParticipant = {
  id: string
  stage: string
  source: string
  rosterLabel?: string
  rosterStatus?: string
  dutyRegisteredLabel?: string
  dutyRegistered?: unknown
  department?: string
}

export function useRuntimeParticipants(ctx: {
  raw: Ref<AnyRecord | null>
  evidence: ComputedRef<AnyRecord>
  memory: ComputedRef<AnyRecord>
}) {
  const { raw, evidence, memory } = ctx

  function collectEmployeeMentions(value: unknown, out: Map<string, { id: string; stage: string; source: string }>, source: string) {
    if (value == null) return
    if (typeof value === 'string') {
      const match = value.match(/\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b/g) || []
      for (const id of match) {
        if (!out.has(id)) out.set(id, { id, stage: 'mentioned', source })
      }
      return
    }
    if (Array.isArray(value)) {
      for (const item of value) collectEmployeeMentions(item, out, source)
      return
    }
    if (typeof value !== 'object') return
    const row = value as AnyRecord
    const id = firstText(row.employee_id, row.employeeId, row.emp_id, row.empId, row.actor, row.assignee)
    if (id && id.includes('-')) {
      out.set(id, {
        id,
        stage: firstText(row.step, row.stage, row.role, row.phase, row.status, 'loop'),
        source,
      })
    }
    for (const [key, child] of Object.entries(row)) {
      if (key === 'prompt' || key === 'report' || key === 'result' || key === 'steps' || key === 'nodes') {
        collectEmployeeMentions(child, out, source)
      }
    }
  }

  const structuredParticipants = computed(() =>
    asArray(raw.value?.participants)
      .map((item) => {
        const row = asRecord(item)
        const id = firstText(row.employee_id, row.id)
        if (!id) return null
        const role = firstText(row.role_label, row.role)
        const stage = asArray(row.stage_labels).map((x) => asString(x)).filter(Boolean).join(' / ')
          || asArray(row.stages).map((x) => asString(x)).filter(Boolean).join(' / ')
          || 'loop'
        return {
          id,
          stage: role ? `${role} · ${stage}` : stage,
          source: asArray(row.sources).map((x) => asString(x)).filter(Boolean).join(' / ') || 'participants',
          rosterLabel: firstText(row.roster_label, row.roster_status),
          rosterStatus: firstText(row.roster_status),
          dutyRegisteredLabel: firstText(row.duty_registered_label),
          dutyRegistered: row.duty_registered,
          department: firstText(row.department_label, row.department_key),
        }
      })
      .filter(Boolean) as SelfEvolutionParticipant[],
  )

  const teamLanes = computed(() => {
    if (structuredParticipants.value.length) return structuredParticipants.value.slice(0, 12)
    const found = new Map<string, SelfEvolutionParticipant>()
    collectEmployeeMentions(evidence.value.steps_by_open_run, found, 'open run')
    collectEmployeeMentions(evidence.value.recent_rows, found, 'ledger')
    collectEmployeeMentions(memory.value.last_run, found, 'last run')
    collectEmployeeMentions(memory.value.recent_runs, found, 'memory')
    return Array.from(found.values()).slice(0, 12)
  })

  return { structuredParticipants, teamLanes }
}
