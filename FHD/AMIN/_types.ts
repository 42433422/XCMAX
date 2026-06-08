export type AminEmployeeKind = 'core' | 'fixed_extension' | 'extension'

export type AminEmployeeDatabaseLink = {
  routeName: string
  label: string
  description: string
}

export type AminEmployeeStitchPlacement = {
  leftPct: number
  topPct: number
  scale?: number
}

export type AminEmployeeFlowStep = {
  label: string
  detail: string
}

export type AminEmployeeFlowDoc = {
  lead: string
  steps: AminEmployeeFlowStep[]
  notes?: string[]
}

export type AminEmployeeSignalBridge = {
  eventNames: string[]
  handler: (detail: Record<string, unknown>) => void
}

export interface AminEmployeePlugin {
  id: string
  label: string
  kind: AminEmployeeKind
  defaultEnabled?: boolean
  panelTitle?: string
  databaseLink?: AminEmployeeDatabaseLink
  stitchPlacement?: AminEmployeeStitchPlacement
  flowDoc?: AminEmployeeFlowDoc
  signalBridges?: AminEmployeeSignalBridge[]
}
