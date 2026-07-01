// CI SSOT: generated from config/neuro_bus_events.yaml — DO NOT EDIT BY HAND
// 改事件契约请编辑该 yaml 后运行: python scripts/dev/neuro_bus_events_ssot.py generate --apply


export type AgentRunEventType =
  | 'artifact.attached'
  | 'billing.debit_failed'
  | 'billing.debited'
  | 'billing.insufficient_balance'
  | 'billing.record_failed'
  | 'billing.recorded'
  | 'billing.refund_failed'
  | 'billing.refund_pending'
  | 'billing.refund_recorded'
  | 'billing.refunded'
  | 'budget.exceeded'
  | 'dataset.ingest_failed'
  | 'dataset.ingested'
  | 'llm.completed'
  | 'llm.failed'
  | 'memory.failed'
  | 'memory.recalled'
  | 'observation.recorded'
  | 'planner.blocked'
  | 'planner.completed'
  | 'planner.started'
  | 'rag.failed'
  | 'rag.retrieved'
  | 'run.completed'
  | 'run.continue_ignored'
  | 'run.created'
  | 'run.failed'
  | 'step.approved'
  | 'step.blocked'
  | 'step.llm_repair_failed'
  | 'step.llm_repair_requested'
  | 'step.repair_applied'
  | 'step.repair_rejected'
  | 'step.retry_scheduled'
  | 'step.waiting_user'
  | 'tool.completed'
  | 'tool.failed'
  | 'tool.started';

export const TERMINAL_AGENT_RUN_EVENT_TYPES: ReadonlySet<AgentRunEventType> = new Set([
  'budget.exceeded',
  'planner.blocked',
  'run.completed',
  'run.failed',
]);

export interface AgentRunEvent {
  event_id: string;
  run_id: string;
  event_type: AgentRunEventType;
  message?: string;
  data?: Record<string, unknown>;
  created_at?: string;
}
