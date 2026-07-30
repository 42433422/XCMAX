import type { ShipmentTask } from './useShipmentTask'
import type { ChatAutoAction, ChatPlannerPayload } from '@/types/chat'
import { asRecord, asString } from '@/utils/typeGuards'

export type XcagiChatWindow = Window & {
  __VUE_CHAT_FILL__?: (value: string) => boolean
  setWorkModeFromChat?: (enabled: boolean) => void
  setMonitorModeFromChat?: (enabled: boolean) => void
  refreshWorkModeMonitorList?: () => void
  legacyAutoActionHandler?: (action: ChatAutoAction, userMessage: string) => void
  isProTaskAcquisitionMessage?: (message: string) => boolean
  jarvisSendMessage?: (message: string) => void
}

export type DynamicShipmentTask = ShipmentTask & Record<string, unknown>

export function getXcagiWindow(): XcagiChatWindow {
  return window as XcagiChatWindow
}

export function asShipmentTask(value: unknown): DynamicShipmentTask {
  const row = asRecord(value)
  return {
    ...row,
    type: asString(row.type),
  } as DynamicShipmentTask
}

export function asPlannerPayload(value: unknown): ChatPlannerPayload {
  return asRecord(value) as ChatPlannerPayload
}

export function asAutoAction(value: unknown): ChatAutoAction {
  return asRecord(value) as ChatAutoAction
}

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : asString(err, fallback)
}

export function isDatabaseTokenRequirement(tokenName?: unknown, tokenDescription?: unknown): boolean {
  const raw = `${String(tokenName || '')} ${String(tokenDescription || '')}`.toUpperCase()
  return /DB_(READ|WRITE)_TOKEN|DATABASE TOKEN|数据库.*令牌|一级|二级|写入令牌|查看令牌/.test(raw)
}
