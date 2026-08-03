import { asArray, asRecord, asString } from '@/utils/typeGuards'

const EXECUTION_EVENT_TYPES = new Set([
  'tool.started',
  'tool.completed',
  'tool.failed',
  'step.waiting_user',
  'step.blocked',
])

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
