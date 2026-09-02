// WorkbenchHomeView 领域类型（逐字迁出，仅加 export）。
import type { LlmProviderBlock } from '../../composables/llmCatalogModelHelpers'
import type { ChatAttachmentMeta } from '../../utils/conversationStore'
import type { OfficeFormat } from '../../utils/officeEmployeeOrchestration'
import type { OrchStepLike } from '../../utils/orchestrationSteps'
import type { RouteLocationRaw } from 'vue-router'

export interface WorkbenchStateRecord {
  [key: string]: unknown
  id?: string | number
  k?: string
  role?: string
  content?: string
  status?: string
  phase?: string
  intent?: string
  intentKey?: string
  intentTitle?: string
  title?: string
  subtitle?: string
  label?: string
  name?: string
  description?: string
  provider?: string
  model?: string
  category?: string
  error?: string
  message?: string
  fullBrief?: string
  displayBrief?: string
  initialBrief?: string
  summaryTitle?: string
  summaryText?: string
  planError?: string
  streamingText?: string
  checklistText?: string
  workflowName?: string
  workflow_name?: string
  employeeWorkflowName?: string
  planNotes?: string
  suggestedModId?: string
  employeeTarget?: string
  fhdBaseUrl?: string
  employeeRoutingBrief?: string
  mod_id?: string
  pack_id?: string | number
  skill_group_name?: string
  primaryLabel?: string
  secondaryLabel?: string
  execution_mode?: string
  loading?: boolean
  summaryNeedsClarification?: boolean
  generateFrontend?: boolean
  sandboxOk?: boolean
  sandbox_ok?: boolean
  passed?: boolean
  critical_failed?: boolean
  runnable?: boolean
  configured?: boolean
  fernet_configured?: boolean
  messages?: WorkbenchStateRecord[]
  planningMessages?: WorkbenchStateRecord[]
  checklistLines?: string[]
  files?: WorkbenchStateRecord[]
  steps?: OrchStepLike[]
  providers?: WorkbenchStateRecord[]
  models?: string[]
  models_detailed?: WorkbenchStateRecord[]
  items?: WorkbenchStateRecord[]
  outputs?: WorkbenchStateRecord[]
  usageLines?: string[]
  validationErrors?: string[]
  llmWarnings?: string[]
  validation_errors?: string[]
  llm_warnings?: string[]
  artifact?: WorkbenchStateRecord | string
  quality_report?: WorkbenchStateRecord
  workflow_attachment?: WorkbenchStateRecord
  manifest?: WorkbenchStateRecord
  embedding?: WorkbenchStateRecord
  preferences?: { provider?: string; model?: string }
  category_labels?: Record<string, string>
  dimensions?: WorkbenchStateRecord
  entries?: WorkbenchStateRecord[]
  workflow_id?: string | number
  skill_group_id?: string | number
  script_workflow_id?: string | number
  primaryRoute?: RouteLocationRaw | null
  secondaryRoute?: RouteLocationRaw | null
}

export interface CachedWorkbenchFile {
  name: string
  size: number
  type: string
  cachedOnly: true
}

export interface PlanMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface PlanSession {
  intentKey: string
  intentTitle: string
  phase: string
  initialBrief: string
  fullBrief: string
  displayBrief: string
  generateFrontend: boolean
  summaryTitle: string
  summaryText: string
  summaryNeedsClarification: boolean
  files: File[]
  messages: PlanMessage[]
  checklistText: string
  checklistLines: string[]
  planError: string
  loading: boolean
  streamingText: string
}

export interface PendingHandoff {
  description: string
  employeeRoutingBrief?: string
  planningContext?: string
  intentTitle: string
  intentKey: string
  workflowName: string
  planNotes: string
  suggestedModId: string
  generateFrontend: boolean
  employeeTarget: string
  employeeWorkflowName: string
  fhdBaseUrl: string
  planningMessages: PlanMessage[]
  executionChecklist?: string[]
  sourceDocuments?: Record<string, unknown>[]
  files?: File[]
}

export interface WorkbenchLlmProvider extends LlmProviderBlock {
  provider: string
  title?: string
  items?: WorkbenchLlmProvider[]
}

export interface WorkbenchLlmCatalog {
  providers: WorkbenchLlmProvider[]
  preferences?: { provider?: string; model?: string }
  category_labels?: Record<string, string>
  fernet_configured?: boolean
}

export interface WorkbenchScriptOutput {
  filename: string
  download_url: string
}

export interface WorkbenchScriptResult {
  outputs?: WorkbenchScriptOutput[]
  stderr?: string
  stdout?: string
}

export interface WorkbenchOrchestrationSession {
  [key: string]: unknown
  session_id?: string
  status?: string
  error?: string
  intent?: string
  workflow_name?: string
  steps?: OrchStepLike[]
  artifact?: WorkbenchStateRecord
  script_result?: WorkbenchScriptResult
  validate_warnings?: string[]
}

export interface WorkbenchCompletionResult {
  intent: string
  title: string
  subtitle: string
  usageLines: string[]
  primaryLabel: string
  primaryRoute: RouteLocationRaw | null
  secondaryLabel: string
  secondaryRoute: RouteLocationRaw | null
}

export interface WorkflowLinkOffer {
  workflowId: string | number
  workflowName: string
  validationErrors: string[]
  llmWarnings: string[]
  sandboxOk: boolean
}

export interface OpenPlanSessionInput {
  fullBrief?: string
  displayBrief?: string
  files?: File[]
  generateFrontend?: boolean
}

export type DirectAttachment = {
  id: string
  name: string
  size: number
  status: ChatAttachmentMeta['status']
  purpose?: string
  docId?: string
  imageDataUrl?: string
  extractedText?: string
  error?: string
  ingesting?: boolean
  ingestError?: string
  readEmployeeId?: string
  embedding?: Record<string, unknown> | null
  file: File
}

export type DirectGeneratingFileState = { active: true; format: OfficeFormat; label?: string }

export type DirectEmployeeOption = { id: string; name: string; sourceLabel: string }

export type DirectWebSearchResult = {
  contextPack: string
  citations: Array<{ title: string; url?: string }>
  note: string
}

export type SiriOrbMode = 'idle' | 'listening' | 'processing' | 'reporting'

export type DirectKbResult = {
  knowledgePack: string
  citations: Array<{ title: string; snippet?: string; url?: string }>
}

export interface KnowledgeChunk {
  text?: string
  content?: string
  snippet?: string
  source?: string
  document_id?: string
  filename?: string
  page_no?: number
  pageNo?: number
}

export interface KnowledgeRetrieveResponse {
  chunks?: KnowledgeChunk[]
  items?: KnowledgeChunk[]
}

export type PlanChoice = { id: string; label: string }

export type PlanQuestion = { id: string; title: string; choices: PlanChoice[] }
