import { ref } from 'vue'
import { resolveErpApiPath } from '@/utils/erpDomainPaths'
import { authenticatedRequestInit } from '@/utils/authenticatedRequest'

export interface PrintResult {
  success: boolean
  message: string
  postPrintReceipt?: string
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

type ApiResultPayload = {
  success?: boolean
  message?: string
  updated?: boolean
  post_print_receipt?: string
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || '未知错误')
}

export function usePrintService() {
  const isPrinting = ref(false)

  async function printLabel(filePath: string, copies: number = 1): Promise<PrintResult> {
    try {
      const requestInit = await authenticatedRequestInit('POST', {
        'Content-Type': 'application/json',
      })
      const resp = await fetch(resolveErpApiPath('/api/print/label'), {
        method: 'POST',
        ...requestInit,
        // This call only runs after the user clicks “开始打印”; that click is
        // the explicit confirmation for both labels and the shipment document.
        body: JSON.stringify({ file_path: filePath, copies, require_confirm: false })
      })
      const data = (await resp.json().catch(() => ({}))) as ApiResultPayload

      if (resp.ok && data?.success) {
        return { success: true, message: '标签打印成功' }
      } else {
        return {
          success: false,
          message: data?.message || `HTTP ${resp.status}`
        }
      }
    } catch (e: unknown) {
      return {
        success: false,
        message: errorMessage(e)
      }
    }
  }

  async function printDocument(
    filePath: string,
    printToken: string = '',
    orderId?: number,
  ): Promise<PrintResult> {
    try {
      const requestInit = await authenticatedRequestInit('POST', {
        'Content-Type': 'application/json',
      })
      const resp = await fetch(resolveErpApiPath('/api/print/document'), {
        method: 'POST',
        ...requestInit,
        body: JSON.stringify({
          file_path: filePath,
          print_token: printToken,
          ...(orderId ? { order_id: orderId } : {}),
        })
      })
      const data = (await resp.json().catch(() => ({}))) as ApiResultPayload

      if (resp.ok && data?.success) {
        return {
          success: true,
          message: '发货单打印成功',
          postPrintReceipt: String(data.post_print_receipt || '').trim() || undefined,
        }
      } else {
        return {
          success: false,
          message: data?.message || `HTTP ${resp.status}`
        }
      }
    } catch (e: unknown) {
      return {
        success: false,
        message: errorMessage(e)
      }
    }
  }

  async function markAsPrinted(
    filePath: string,
    orderId?: number,
    postPrintReceipt: string = '',
  ): Promise<PrintResult> {
    if (!postPrintReceipt.trim()) {
      return {
        success: false,
        message: '缺少本次实际打印回执，未更新发货单打印状态',
      }
    }
    try {
      const payload: Record<string, unknown> = {
        file_path: filePath,
        post_print_receipt: postPrintReceipt,
      }
      if (orderId) {
        payload.order_id = orderId
      }

      const resp = await fetch(resolveErpApiPath('/api/shipment/print'), {
        method: 'POST',
        ...(await authenticatedRequestInit('POST', {
          'Content-Type': 'application/json',
        })),
        body: JSON.stringify(payload)
      })
      const data = (await resp.json().catch(() => ({}))) as ApiResultPayload

      if (resp.ok && data?.success && data?.updated !== false) {
        return { success: true, message: '打印状态已更新' }
      } else {
        return {
          success: false,
          message: data?.message || '更新失败'
        }
      }
    } catch (e: unknown) {
      return {
        success: false,
        message: errorMessage(e)
      }
    }
  }

  async function executePrintTask(
    labelPaths: string[],
    filePath: string,
    orderId?: number,
    _purchaseUnit?: string,
    printToken: string = '',
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
      const docResult = await printDocument(filePath, printToken, orderId)
      summary.shipmentPrinted = docResult.success

      if (!docResult.success) {
        summary.logs.push(`发货单打印失败：${docResult.message}`)
      }

      if (!orderId) {
        summary.logs.push('打印状态未落库：缺少记录ID')
      } else if (!docResult.success) {
        summary.logs.push('打印状态未落库：发货单未成功提交打印')
      } else {
        const markResult = await markAsPrinted(filePath, orderId, docResult.postPrintReceipt)
        summary.shipmentMarked = markResult.success

        if (!markResult.success) {
          summary.logs.push(`打印状态更新失败：${markResult.message}`)
        }
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
