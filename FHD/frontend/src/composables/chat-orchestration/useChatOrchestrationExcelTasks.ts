/**
 * useChatOrchestration 拆出的 Excel 分析任务回调装配（行为零变更）。
 */
import type { Ref } from 'vue'
import type { useChatResponseAttach } from '../useChatResponseAttach'
import type { useChatTaskList } from '../useChatTaskList'
import {
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
} from '../useChatPersistence'
import { useExcelAnalysis } from '../useExcelAnalysis'
import type { useChatExcelContext } from '../useChatExcelContext'
import { getXcagiWindow } from './chatOrchestrationShared'

type TaskListApi = ReturnType<typeof useChatTaskList>
type ExcelCtxApi = ReturnType<typeof useChatExcelContext>

export interface ChatOrchestrationExcelTasksDeps {
  sessionId: Ref<string>
  addMessage: ReturnType<typeof import('../useChatMessages')['useChatMessages']>['addMessage']
  saveMessage: ReturnType<typeof import('../useChatMessages')['useChatMessages']>['saveMessage']
  lastExcelAnalysisContext: ExcelCtxApi['lastExcelAnalysisContext']
  linkedExcelAllSheets: ExcelCtxApi['linkedExcelAllSheets']
  linkedExcelSheet: ExcelCtxApi['linkedExcelSheet']
  onMultimodalFileChange: ExcelCtxApi['onMultimodalFileChange']
  taskList: TaskListApi['taskList']
  createTaskId: TaskListApi['createTaskId']
  upsertTask: TaskListApi['upsertTask']
  finishTask: TaskListApi['finishTask']
  failTask: TaskListApi['failTask']
  getLastAiMessageRef: ReturnType<typeof useChatResponseAttach>['getLastAiMessageRef']
}

export function useChatOrchestrationExcelTasks(deps: ChatOrchestrationExcelTasksDeps) {
  const {
    sessionId,
    addMessage,
    saveMessage,
    lastExcelAnalysisContext,
    linkedExcelAllSheets,
    linkedExcelSheet,
    onMultimodalFileChange,
    taskList,
    createTaskId,
    upsertTask,
    finishTask,
    failTask,
    getLastAiMessageRef,
  } = deps

  const { excelAnalyzeUploading, excelAnalyzeInputRef, triggerUpload, onExcelAnalyzeFileChange, setOnMultimodalFileChangeCallback } =
    useExcelAnalysis(
      { addMessage, saveMessage },
      {
        onAnalyzed: ({ fileName, summary, result }) => {
          const persistedPath = resolveExcelFilePathFromAnalysis(result)
          const payload = {
            file_name: fileName,
            ...(persistedPath ? { file_path: persistedPath } : {}),
            summary,
            fields: Array.isArray(result?.fields) ? result.fields : [],
            preview_data: result?.preview_data || {},
            sheets: Array.isArray(result?.sheets) ? result.sheets : [],
          }
          lastExcelAnalysisContext.value = payload
          linkedExcelAllSheets.value = false
          const sheetOptions = resolveExcelSheetOptionsFromContext(payload)
          linkedExcelSheet.value = sheetOptions[0] || null
          window.dispatchEvent(
            new CustomEvent('xcagi:excel-sheet-context', {
              detail: {
                select_all_sheets: false,
                selected_sheet: linkedExcelSheet.value,
                excel_analysis: payload,
              },
            }),
          )
          const sid = String(sessionId.value || '').trim() || 'default'
          persistExcelAnalysisContext(sid, payload)
          window.requestAnimationFrame(() => {
            const displayFileName =
              String(fileName || '').trim() ||
              String(persistedPath || '')
                .split(/[\\/]/)
                .pop() ||
              'excel.xlsx'
            const prefix = `@uploads/${displayFileName} `
            const fillInput = getXcagiWindow().__VUE_CHAT_FILL__
            if (typeof fillInput === 'function' && fillInput(prefix)) return

            // 兜底：当宿主未注入 __VUE_CHAT_FILL__ 时，仍尝试直接写 DOM。
            const msgInput = document.querySelector('#view-chat #messageInput') as HTMLTextAreaElement | null
            if (msgInput) {
              msgInput.value = prefix
              msgInput.dispatchEvent(new Event('input', { bubbles: true }))
              msgInput.focus()
            }
          })
          const task = taskList.value.find((t) => t.type === 'excel_analyze' && t.status === 'running')
          if (task) {
            upsertTask({
              id: task.id,
              title: task.title,
              type: task.type,
              source: task.source,
              status: 'success',
              progress: 100,
              stage: '分析完成',
              summary,
              error: '',
              messageRef: getLastAiMessageRef(),
            })
          }
        },
        onAnalyzeStart: ({ fileName }) => {
          upsertTask({
            id: createTaskId('excel'),
            title: `分析Excel：${fileName}`,
            type: 'excel_analyze',
            source: 'excel',
            status: 'running',
            progress: 5,
          })
        },
        onAnalyzeProgress: ({ step, progress }) => {
          const task = taskList.value.find((t) => t.type === 'excel_analyze' && t.status === 'running')
          if (!task) return
          upsertTask({
            id: task.id,
            title: task.title,
            type: task.type,
            source: task.source,
            status: 'running',
            progress: progress ?? task.progress,
            stage: step,
          })
        },
        onAnalyzeDone: ({ success, message }) => {
          const task = taskList.value.find((t) => t.type === 'excel_analyze' && t.status === 'running')
          if (!task) return
          if (success) {
            finishTask(task.id, task.summary || 'Excel 分析完成')
          } else {
            failTask(task.id, message || 'Excel 分析失败')
          }
        },
      },
    )

  setOnMultimodalFileChangeCallback(onMultimodalFileChange)

  return {
    excelAnalyzeUploading,
    excelAnalyzeInputRef,
    triggerUpload,
    onExcelAnalyzeFileChange,
  }
}
