// useModAuthoring 拆分模块共享的内部类型与常量（自原单体实现原样迁移，行为零变更）。
import type { LooseRecord } from '../../types'

export interface WorkflowEmployeeViewRow {
  index: number
  raw: LooseRecord
  id: string
  label: string
  panelTitle: string
  title: string
  bodyFull: string
  bodyShort: string
  isEmpty: boolean
  linkedWorkflowId: number
  readiness: LooseRecord | null
  ready: boolean
}

export interface ModManifest extends LooseRecord {
  name?: string
  version?: string
  description?: string
  config?: LooseRecord
  frontend?: LooseRecord
  employee_config_v2?: LooseRecord
  industry?: LooseRecord
  backend?: LooseRecord
  workflow_employees?: unknown[]
  artifact?: string
  kind?: string
}

export interface ModAuthoringData extends LooseRecord {
  id?: string
  validation_ok?: boolean
  manifest?: ModManifest
  files?: unknown[]
}

export interface ModAuthoringSummary extends LooseRecord {
  blueprint_file?: string
  validation_ok?: boolean
  warnings?: unknown[]
  blueprint_routes?: Array<{ methods?: string[]; path?: string }>
}

export interface SnapshotRow extends LooseRecord {
  snap_id: string
  created_at: number
  label?: string
}

export interface EmployeePickRow {
  pickKey: string
  id: string
  name: string
  version: string
  description: string
  sourceLabel: string
  catalogPkgId?: string
}

export const PREFILL_KEY = 'modstore_employee_prefill'

export const EMP_ID_RE = /^[a-z][a-z0-9_-]{0,63}$/
