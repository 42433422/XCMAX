/**
 * Employee AI draft pipeline types & reducer (domain).
 *
 * 运行时：SSE 由 `useAgentLoop().runEmployeeDraft` 消费；流水线快照与审核会话在 `useWorkbenchStore`。
 */

export type {
  EmployeeDraftReviewMessage,
  IntentData,
  PipelineStages,
  PipelineStatus,
  PricingData,
  SkillData,
  StageState,
  StageStatus,
  V2Data,
  WorkflowData,
} from '../domain/employeeDraftPipeline'

export {
  applyEmployeeDraftPipelineEvent,
  makePipelineStatus,
  makeStages,
} from '../domain/employeeDraftPipeline'
