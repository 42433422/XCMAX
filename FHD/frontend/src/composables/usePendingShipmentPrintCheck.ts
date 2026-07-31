/** Pending shipment print status check (extracted for source-governance). */
import type { Ref } from 'vue'

type AnyTask = Record<string, any> | null | undefined

export function createPendingShipmentPrintChecker(deps: {
  currentTask: Ref<AnyTask>
  lastShipmentExecution: Ref<AnyTask>
  addAndSaveMessage: (content: string, role: string) => Promise<void> | void
  createTaskId: (prefix: string) => string
  upsertTask: (task: Record<string, any>) => void
  checkDocumentPrintJob: (token: string) => Promise<any>
  // remaining body uses more deps — keep as injected callbacks pack
  run: (ctx: {
    currentTask: Ref<AnyTask>
    lastShipmentExecution: Ref<AnyTask>
    addAndSaveMessage: (content: string, role: string) => Promise<void> | void
    createTaskId: (prefix: string) => string
    upsertTask: (task: Record<string, any>) => void
    checkDocumentPrintJob: (token: string) => Promise<any>
  }) => Promise<void>
}) {
  return async function checkPendingShipmentPrintFromTaskCard() {
    await deps.run(deps)
  }
}
