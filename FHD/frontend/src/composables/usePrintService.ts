import { ref } from 'vue'
import { resolveErpApiPath } from '@/utils/erpDomainPaths'
import { authenticatedRequestInit } from '@/utils/authenticatedRequest'

export interface PrintResult {
  success: boolean
  message: string
  postPrintReceipt?: string
  /** False only when the operating system accepted the job but has not confirmed it printed. */
  printCompleted?: boolean
  printPending?: boolean
  printState?: string
  jobId?: string
  /** Opaque, owner-bound token for rechecking an unconfirmed CUPS job. */
  printJobToken?: string
  printTrackingAvailable?: boolean
}

export interface PrintSummary {
  labelSuccess: number
  labelFailed: number
  /** Labels are optional for a delivery note when no label printer is configured. */
  labelSkipped?: number
  shipmentPrinted: boolean
  shipmentMarked: boolean
  /** A CUPS job can be accepted while still waiting for the physical printer. */
  shipmentPending?: boolean
  pending?: boolean
  pendingPrintJobToken?: string
  printTrackingAvailable?: boolean
  logs: string[]
  success: boolean
  message: string
}

type ApiResultPayload = {
  success?: boolean
  message?: string
  updated?: boolean
  post_print_receipt?: string
  print_completed?: boolean
  print_state?: string
  job_id?: string
  print_job_token?: string
  print_tracking_available?: boolean
  summary?: {
    label_printer_ready?: boolean
  }
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
        const printPending = data.print_completed === false
          || ['queued', 'pending', 'processing'].includes(String(data.print_state || '').toLowerCase())
        return {
          success: true,
          message: String(data.message || (printPending ? '发货单已提交打印队列，等待设备完成' : '发货单打印成功')),
          postPrintReceipt: String(data.post_print_receipt || '').trim() || undefined,
          printCompleted: !printPending,
          printPending,
          printState: String(data.print_state || '').trim() || undefined,
          jobId: String(data.job_id || '').trim() || undefined,
          printJobToken: String(data.print_job_token || '').trim() || undefined,
          printTrackingAvailable: typeof data.print_tracking_available === 'boolean'
            ? data.print_tracking_available
            : undefined,
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

  async function checkDocumentPrintJob(printJobToken: string): Promise<PrintResult> {
    const token = String(printJobToken || '').trim()
    if (!token) {
      return { success: false, message: '缺少待确认打印任务凭据' }
    }
    try {
      const resp = await fetch(
        resolveErpApiPath(`/api/print/jobs/${encodeURIComponent(token)}`),
        await authenticatedRequestInit('GET'),
      )
      const data = (await resp.json().catch(() => ({}))) as ApiResultPayload
      const state = String(data.print_state || '').trim().toLowerCase()
      const pending = data.print_completed === false || ['queued', 'pending', 'processing'].includes(state)
      const completed = data.print_completed === true || state === 'completed'
      if (resp.ok && data?.success) {
        return {
          success: true,
          message: String(data.message || (completed ? '发货单已确认打印完成' : '发货单仍在打印队列中')),
          postPrintReceipt: String(data.post_print_receipt || '').trim() || undefined,
          printCompleted: completed,
          printPending: pending,
          printState: state || undefined,
        }
      }
      return {
        success: false,
        message: String(data.message || `HTTP ${resp.status}`),
        printCompleted: completed,
        printPending: pending,
        printState: state || undefined,
      }
    } catch (e: unknown) {
      return { success: false, message: errorMessage(e) }
    }
  }

  async function labelPrinterReady(): Promise<boolean | null> {
    try {
      const resp = await fetch(resolveErpApiPath('/api/print/printers'), await authenticatedRequestInit('GET'))
      const data = (await resp.json().catch(() => ({}))) as ApiResultPayload
      if (!resp.ok || !data?.success || typeof data?.summary?.label_printer_ready !== 'boolean') {
        return null
      }
      return data.summary.label_printer_ready
    } catch {
      // Preserve legacy behaviour on a discovery failure: try label printing
      // and surface any real printer error instead of silently dropping it.
      return null
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
      labelSkipped: 0,
      shipmentPrinted: false,
      shipmentMarked: false,
      shipmentPending: false,
      pending: false,
      logs: [],
      success: false,
      message: '',
    }

    const labelReady = labelPaths.length ? await labelPrinterReady() : true
    if (labelPaths.length && labelReady === false) {
      summary.labelSkipped = labelPaths.length
      summary.logs.push(`标签未打印：未配置可用标签打印机（共 ${labelPaths.length} 张，发货单将继续打印）`)
    } else {
      for (const lp of labelPaths) {
        const result = await printLabel(lp)
        if (result.success) {
          summary.labelSuccess++
        } else {
          summary.labelFailed++
          summary.logs.push(`标签打印失败：${result.message}`)
        }
      }
    }

    if (filePath) {
      const docResult = await printDocument(filePath, printToken, orderId)
      summary.shipmentPrinted = docResult.success && docResult.printCompleted !== false

      if (!docResult.success) {
        summary.logs.push(`发货单打印失败：${docResult.message}`)
      } else if (docResult.printPending || docResult.printCompleted === false) {
        summary.shipmentPending = true
        summary.pending = true
        summary.pendingPrintJobToken = docResult.printJobToken
        summary.printTrackingAvailable = docResult.printTrackingAvailable
        summary.logs.push(`发货单已提交打印队列：${docResult.message}；未更新发货单打印状态`)
      }

      if (!orderId) {
        summary.logs.push('打印状态未落库：缺少记录ID')
      } else if (!docResult.success) {
        summary.logs.push('打印状态未落库：发货单未成功提交打印')
      } else if (docResult.printPending || docResult.printCompleted === false) {
        summary.logs.push('打印状态未落库：等待 macOS CUPS 确认物理完成')
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
    // A delivery document is the business side effect that controls shipment
    // state.  Labels are helpful companions: failures remain explicit in the
    // receipt but must not rewrite an already confirmed delivery print back
    // into a failed shipment.
    summary.success = filePath ? shipmentOk : labelsOk
    summary.message =
      summary.logs.join('；') || (summary.success ? '打印完成' : (summary.pending ? '打印任务排队中' : '打印未完全成功'))

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

    const skipped = Number(summary.labelSkipped || 0)
    parts.push(`标签：${summary.labelSuccess}/${labelCount || 0} 成功${skipped ? `，${skipped} 张未打印（未配置标签机）` : ''}`)

    if (filePath) {
      parts.push(`发货单：${summary.shipmentPending ? '已提交队列，等待设备完成' : (summary.shipmentPrinted ? '已确认打印' : '失败')}`)
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
    checkDocumentPrintJob,
    markAsPrinted,
    executePrintTask,
    buildPrintSummaryMessage
  }
}
