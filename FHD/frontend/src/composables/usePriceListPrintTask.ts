import { type Ref } from 'vue'
import { asRecord, asString } from '@/utils/typeGuards'

type ShipmentExecutionState = {
  filePath: string
  purchaseUnit: string
  orderId: number | null
  labelPaths: string[]
}

export interface PriceListTaskSyncDeps {
  lastShipmentExecution: Ref<ShipmentExecutionState | null>
  buildShipmentDownloadUrl: (task: unknown) => string
}

export function syncPriceListTaskToShipmentExecution(
  nextTask: unknown,
  deps: PriceListTaskSyncDeps,
): boolean {
  const row = asRecord(nextTask)
  const data = asRecord(row.data)
  if (row.type !== 'price_list_export' || row.completed !== true) return false

  const filePath = asString(row.file_path || row.filePath || data.file_path)
  const downloadUrl = asString(row.downloadUrl || row.download_url) || deps.buildShipmentDownloadUrl(nextTask)
  if (downloadUrl && !row.downloadUrl) {
    row.downloadUrl = downloadUrl
  }

  if (filePath) {
    deps.lastShipmentExecution.value = {
      filePath,
      purchaseUnit: asString((row.customer_name || data.customer_name)),
      orderId: null,
      labelPaths: [],
    }
  }

  return true
}
