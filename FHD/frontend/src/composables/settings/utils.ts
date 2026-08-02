import type { DeploymentMode } from '@/constants/deploymentModes.generated';

export type ApiMessageResult = {
  success?: boolean
  message?: string
  error?: string
}

export type DistillationVersion = {
  name: string
  label?: string
  modified?: string
  size_kb?: number
}

export type DesktopDeploymentResponse = {
  data?: DesktopDeploymentResponse
  success?: boolean
  desktopMode?: boolean
  modes?: DeploymentMode[]
  currentMode?: string
  database?: {
    storageMode?: string
    sqlitePath?: string
    databaseUrlRedacted?: string
    postgresUrlRedacted?: string
  }
  syncPlan?: {
    syncCommand?: string
    restartRequired?: boolean
  } | null
  restartRequired?: boolean
}

export type DesktopDeploymentUpdateResponse = DesktopDeploymentResponse & {
  data?: DesktopDeploymentUpdateResponse
  mode?: string
  modeDetail?: DeploymentMode
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : String(error || fallback)
}
