import { ref } from 'vue'
import { printApi } from '@/api/print'

export interface PrintResult {
  success: boolean
  message: string
}

export interface PrintSummary {
  labelSuccess: number
  labelFailed: number
  shipmentPrinted: boolean
  shipmentMarked: boolean
  logs: string[]
  success: boolean
  message: string
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '未知错误')
}

export function usePrintService() {
  const isPrinting = ref(false)

  async function printLabel(filePath: string, copies: number = 1): Promise<PrintResult> {
    try {
      const res = await printApi.printLabel({ file_path: filePath, copies })
      if (res?.success) {
        return { success: true, message: '标签打印成功' }
      }
      return { success: false, message: res?.message || '打印失败' }
    } catch (e: unknown) {
      return { success: false, message: errorMessage(e) }
    }
  }

  async function printDocument(filePath: string): Promise<PrintResult> {
    try {
      const res = await printApi.printDocument({ file_path: filePath })
      if (res?.success) {
        return { success: true, message: '发货单打印成功' }
      }
      return { success: false, message: res?.message || '打印失败' }
    } catch (e: unknown) {
      return { success: false, message: errorMessage(e) }
    }
  }

  async function markAsPrinted(filePath: string, orderId?: number): Promise<PrintResult> {
    try {
      const payload: { file_path: string; order_id?: number } = { file_path: filePath }
      if (orderId) {
        payload.order_id = orderId
      }
      const res = await printApi.markShipmentPrinted(payload)
      if (res?.success && res?.updated !== false) {
        return { success: true, message: '打印状态已更新' }
      }
      return { success: false, message: res?.message || '更新失败' }
    } catch (e: unknown) {
      return { success: false, message: errorMessage(e) }
    }
  }

  async function executePrintTask(
    labelPaths: string[],
    filePath: string,
    orderId?: number,
    _purchaseUnit?: string
  ): Promise<PrintSummary> {
    isPrinting.value = true

    const summary: PrintSummary = {
      labelSuccess: 0,
      labelFailed: 0,
      shipmentPrinted: false,
      shipmentMarked: false,
      logs: [],
      success: false,
      message: '',
    }

    for (const lp of labelPaths) {
      const result = await printLabel(lp)
      if (result.success) {
        summary.labelSuccess++
      } else {
        summary.labelFailed++
        summary.logs.push(`标签打印失败：${result.message}`)
      }
    }

    if (filePath) {
      const docResult = await printDocument(filePath)
      summary.shipmentPrinted = docResult.success

      if (!docResult.success) {
        summary.logs.push(`发货单打印失败：${docResult.message}`)
      }

      const markResult = await markAsPrinted(filePath, orderId)
      summary.shipmentMarked = markResult.success

      if (!markResult.success) {
        summary.logs.push(`打印状态更新失败：${markResult.message}`)
      }

      if (!orderId) {
        summary.logs.push('打印状态未落库：缺少记录ID')
      }
    }

    const shipmentOk = !filePath || (summary.shipmentPrinted && summary.shipmentMarked)
    const labelsOk = labelPaths.length === 0 || summary.labelFailed === 0
    summary.success = labelsOk && shipmentOk
    summary.message =
      summary.logs.join('；') || (summary.success ? '打印完成' : '打印未完全成功')

    isPrinting.value = false
    return summary
  }

  function buildPrintSummaryMessage(
    summary: PrintSummary,
    labelCount: number,
    filePath?: string,
    _purchaseUnit?: string
  ): string {
    const parts = ['打印执行完成']

    parts.push(`标签：${summary.labelSuccess}/${labelCount || 0} 成功`)

    if (filePath) {
      parts.push(`发货单：${summary.shipmentPrinted ? '已发送打印' : '失败'}`)
      parts.push(`状态：${summary.shipmentMarked ? '已标记已打印' : '未更新'}`)
    }

    if (summary.logs.length) {
      parts.push(`详情：${summary.logs.slice(0, 2).join('；')}`)
    }

    return parts.filter(Boolean).join('；')
  }

  return {
    isPrinting,
    printLabel,
    printDocument,
    markAsPrinted,
    executePrintTask,
    buildPrintSummaryMessage
  }
}
