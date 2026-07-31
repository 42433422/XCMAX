/** Extracted from useChatOrchestration for source-governance. */

type RefLike<T> = { value: T }

type PendingPrintDeps = {
  currentTask: RefLike<Record<string, unknown> | null | undefined>
  lastShipmentExecution: RefLike<Record<string, unknown> | null | undefined>
  addAndSaveMessage: (content: string, role: string) => Promise<void> | void
  createTaskId: (prefix: string) => string
  upsertTask: (task: Record<string, unknown>) => void
  checkDocumentPrintJob: (token: string) => Promise<Record<string, unknown>>
  markAsPrinted: (...args: unknown[]) => Promise<Record<string, unknown>>
  getLastAiMessageRef: () => { content?: string } | null | undefined
  completeTask: (...args: unknown[]) => void
  failTask: (...args: unknown[]) => void
  syncTaskListEntry: (...args: unknown[]) => void
}

export async function checkPendingShipmentPrintFromTaskCard(deps: PendingPrintDeps) {
  const {
    currentTask,
    lastShipmentExecution,
    addAndSaveMessage,
    createTaskId,
    upsertTask,
    checkDocumentPrintJob,
    markAsPrinted,
    getLastAiMessageRef,
    completeTask,
    failTask,
    syncTaskListEntry,
  } = deps

  const task = currentTask.value as Record<string, unknown> | null | undefined
  const context = lastShipmentExecution.value as Record<string, unknown> | null | undefined
  const jobToken = String(task?.printJobToken || context?.pendingPrintJobToken || '').trim()
  if (!task || task.type !== 'shipment_generate' || !task.printPending || !jobToken) {
    await addAndSaveMessage('没有可查询的待确认打印任务。请重新生成发货单后再打印。', 'ai')
    return
  }
  if (task.printStatusChecking) return

  currentTask.value = { ...task, printStatusChecking: true }
  const statusTaskId = createTaskId('print_status')
  upsertTask({
    id: statusTaskId,
    type: 'print',
    source: 'print',
    title: '打印状态检查',
    status: 'running',
    progress: 70,
    stage: '正在查询 macOS CUPS',
  })

  const result = await checkDocumentPrintJob(jobToken)
  const shipmentListId = String(context?.taskListId || '').trim()
  const filePath = String(context?.filePath || '').trim()
  const orderId = context?.orderId ?? undefined

  if (result.success && result.printCompleted) {
    const markResult = await markAsPrinted(filePath, orderId, result.postPrintReceipt)
    if (markResult.success) {
      const successText = 'macOS CUPS 已确认发货单打印完成，已更新发货记录打印状态。'
      await addAndSaveMessage(successText, 'ai')
      currentTask.value = {
        ...task,
        printPending: false,
        printStatusChecking: false,
        printCompleted: true,
        printTerminal: false,
        printJobToken: undefined,
        description: `${String(task.description || '').trim()}\n${successText}`.trim(),
      }
      if (lastShipmentExecution.value) {
        lastShipmentExecution.value = {
          ...lastShipmentExecution.value,
          pendingPrintJobToken: undefined,
        }
      }
      upsertTask({
        id: statusTaskId,
        type: 'print',
        source: 'print',
        title: '打印状态检查',
        status: 'success',
        progress: 100,
        summary: successText,
        messageRef: getLastAiMessageRef(),
      })
      if (shipmentListId) {
        upsertTask({
          id: shipmentListId,
          type: 'shipment',
          source: 'shipment',
          title: '发货单生成任务',
          status: 'success',
          progress: 100,
          summary: successText,
          messageRef: getLastAiMessageRef(),
        })
      }
      await runShipmentMgmtAfterPrintSuccess({
        purchaseUnit: String(context?.purchaseUnit || '').trim(),
        orderId: context?.orderId ?? null,
        filePath,
        labelCount: Array.isArray(context?.labelPaths) ? context.labelPaths.length : 0,
      })
      return
    }

    const failureText = `macOS CUPS 已确认打印完成，但发货记录未更新：${markResult.message}。请重新生成发货单后再处理。`
    await addAndSaveMessage(failureText, 'ai')
    currentTask.value = {
      ...task,
      printPending: false,
      printStatusChecking: false,
      printTerminal: true,
      description: `${String(task.description || '').trim()}\n${failureText}`.trim(),
    }
    upsertTask({
      id: statusTaskId,
      type: 'print',
      source: 'print',
      title: '打印状态检查',
      status: 'failed',
      progress: 100,
      error: failureText,
      messageRef: getLastAiMessageRef(),
    })
    return
  }

  if (result.success && result.printPending) {
    const pendingText = 'macOS CUPS 仍在等待打印机完成；未标记已打印，可稍后再次点击“检查打印状态”。'
    await addAndSaveMessage(pendingText, 'ai')
    currentTask.value = {
      ...task,
      printPending: true,
      printStatusChecking: false,
      description: `${String(task.description || '').trim()}\n${pendingText}`.trim(),
    }
    upsertTask({
      id: statusTaskId,
      type: 'print',
      source: 'print',
      title: '打印状态检查',
      status: 'running',
      progress: 85,
      stage: '等待打印机完成',
      summary: pendingText,
      messageRef: getLastAiMessageRef(),
    })
    return
  }

  const terminal = ['aborted', 'unknown'].includes(String(result.printState || '').toLowerCase())
  const failureText = terminal
    ? `打印任务无法完成：${result.message}。请重新生成发货单后再打印。`
    : `暂时无法查询打印状态：${result.message}。可稍后再次点击“检查打印状态”。`
  await addAndSaveMessage(failureText, 'ai')
  currentTask.value = {
    ...task,
    printPending: !terminal,
    printStatusChecking: false,
    printTerminal: terminal,
    description: `${String(task.description || '').trim()}\n${failureText}`.trim(),
  }
  upsertTask({
    id: statusTaskId,
    type: 'print',
    source: 'print',
    title: '打印状态检查',
    status: terminal ? 'failed' : 'running',
    progress: terminal ? 100 : 85,
    stage: terminal ? '打印任务已中止' : '等待再次检查',
    error: terminal ? failureText : '',
    summary: failureText,
    messageRef: getLastAiMessageRef(),
  })
  if (terminal && shipmentListId) {
    upsertTask({
      id: shipmentListId,
      type: 'shipment',
      source: 'shipment',
      title: '发货单生成任务',
      status: 'failed',
      stage: '打印任务未完成',
      error: failureText,
      summary: '发货单未标记已打印；请重新生成后再提交打印。',
    })
  }
}
