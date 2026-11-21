import type { AgentRun } from '@/api/agentRuns'
import { asArray, asRecord, asString } from '@/utils/typeGuards'

const EXECUTION_EVENT_TYPES = new Set(['tool.started', 'tool.completed', 'tool.failed', 'step.waiting_user', 'step.blocked'])

/** A chat lifecycle is not an agent execution. Show task state only with execution evidence. */
export function hasAgentRunExecutionEvidence(events: unknown): boolean {
  return asArray(events).some((event) => {
    const row = asRecord(event)
    return EXECUTION_EVENT_TYPES.has(asString(row.event_type).trim())
  })
}

export function hasConfirmedAgentRunExecution(events: unknown): boolean {
  return asArray(events).some((event) => {
    const row = asRecord(event)
    return asString(row.event_type).trim() === 'tool.completed'
  })
}

export function runHasUncertainReceipt(run: AgentRun): boolean {
  const recovery = run.metadata?.recovery as { state?: string } | undefined
  const nodeOutputs = asRecord(run.final_output?.node_outputs)
  const outputs = [run.final_output, ...Object.values(nodeOutputs).map(asRecord), ...(run.steps || []).map((step) => step.output)]
  const completed = ['completed', 'success'].includes(run.status)
  return (
    run.status === 'unknown' ||
    recovery?.state === 'manual_reconciliation_required' ||
    outputs.some((output) => {
      const signals = [output?.outcome, output?.execution_outcome, output?.execution_state, output?.status,
        output?.agent_status, output?.run_status, asRecord(output?.data).agent_status, asRecord(output?.data).run_status].map((value) =>
        String(value || '')
          .trim()
          .toLowerCase(),
      )
      return (
        output?.reconciliation_required === true || output?.requires_reconciliation === true || output?.outcome_unknown === true ||
        signals.some((value) => ['unknown', 'outcome_unknown'].includes(value)) ||
        (completed &&
          (output?.success === false ||
            output?.pending_approval === true ||
            output?.requires_token === true ||
            signals.some((value) =>
              [
                'waiting',
                'pending',
                'accepted',
                'inflight',
                'in_progress',
                'waiting_approval',
                'waiting_user',
                'waiting_input',
                'waiting_auth',
                'pending_approval',
                'approval_required',
                'failed',
                'failure',
                'fail',
                'error',
                'cancelled',
                'canceled',
                'blocked',
                'running',
                'queued',
                'retrying',
                'paused',
              ].includes(value),
            )))
      )
    })
  )
}
