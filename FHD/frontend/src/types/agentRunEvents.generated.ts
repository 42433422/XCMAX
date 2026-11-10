// CI SSOT: generated from config/neuro_bus_events.yaml — DO NOT EDIT BY HAND
// 改事件契约请编辑该 yaml 后运行: python scripts/dev/neuro_bus_events_ssot.py generate --apply


export type AgentRunEventType =
  | 'approval.authorization_mismatch'
  | 'approval.rejected'
  | 'approval.resume_plan_rejected'
  | 'approval.resume_proof_missing'
  | 'approval.timed_out'
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
  | 'run.clarification_resumed'
  | 'run.completed'
  | 'run.continue_ignored'
  | 'run.created'
  | 'run.failed'
  | 'run.idempotency_conflict'
  | 'run.observation_interrupted'
  | 'step.approved'
  | 'step.blocked'
  | 'step.clarification_required'
  | 'step.llm_repair_failed'
  | 'step.llm_repair_requested'
  | 'step.repair_applied'
  | 'step.repair_rejected'
  | 'step.retry_scheduled'
  | 'step.skipped'
  | 'step.waiting_user'
  | 'task.approval_required'
  | 'task.child_run_attached'
  | 'tool.completed'
  | 'tool.failed'
  | 'tool.permission_denied'
  | 'tool.receipt_observed'
  | 'tool.started'
  | 'workflow.concrete_params_rejected'
  | 'workflow.graph_rejected'
  | 'workflow.plan_audit_rejected'
  | 'workflow.plan_audited'
  | 'workflow.plan_node_updated'
  | 'workflow.plan_policy_normalized'
  | 'workflow.plan_policy_rejected'
  | 'workflow.plan_reference_resolved';

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
