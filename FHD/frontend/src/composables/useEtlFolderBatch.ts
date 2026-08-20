import { computed, onBeforeUnmount, ref, type Ref } from 'vue'
import type { Router } from 'vue-router'

import { etlApi, type EtlCapabilities, type EtlRun } from '@/api/etl'
import {
  ETL_MAX_FILE_BYTES,
  formatEtlBytes,
  selectEtlSourceFiles,
  type EtlIgnoredSourceFile,
  type EtlSelectedSourceFile,
} from '@/utils/etlFileSelection'
import { tabForRunStatus, type EtlRunTab } from '@/utils/etlRunView'

export type BatchFileStatus =
  | 'waiting'
  | 'uploading'
  | 'creating'
  | 'queued'
  | 'previewing'
  | 'preview_ready'
  | 'executing'
  | 'completed'
  | 'failed'
  | 'interrupted'

export type EtlBatchFile = EtlSelectedSourceFile & {
  status: BatchFileStatus
  progress: number
  runId?: string
  message?: string
}

type EtlFolderBatchOptions = {
  capabilities: Ref<EtlCapabilities | null>
  targetType: Ref<string>
  templateId: Readonly<Ref<string>>
  compatibilityPresetId: Readonly<Ref<string>>
  targetConfigId: Ref<string>
  runs: Ref<EtlRun[]>
  currentRun: Ref<EtlRun | null>
  activeTab: Ref<EtlRunTab>
  busy: Ref<boolean>
  pageError: Ref<string>
  router: Router
  /** 默认 true：解析就绪后自动写入业务库，而非停在预演确认。 */
  autoWriteEnabled: Ref<boolean>
  markAutoWrite: (runId: string) => void
  tryAutoWrite: (run: EtlRun) => Promise<void>
  syncDraft: () => void
  schedulePoll: () => void
  loadRows: () => Promise<void>
}

const PARSE_DONE_STATUSES = new Set<BatchFileStatus>(['preview_ready', 'completed', 'failed', 'interrupted'])

const WRITE_TERMINAL_STATUSES = new Set<BatchFileStatus>(['completed', 'failed', 'interrupted'])

function newBatchId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, (character) => {
    const value = Number(character)
    const random = globalThis.crypto.getRandomValues(new Uint8Array(1))[0]
    return (value ^ (random & (15 >> (value / 4)))).toString(16)
  })
}

export function batchFileStatusLabel(status: BatchFileStatus) {
  return (
    {
      waiting: '等待上传',
      uploading: '上传中',
      creating: '创建任务',
      queued: '已排队',
      previewing: '解析中',
      preview_ready: '待写入',
      executing: '写入中',
      completed: '已写入',
      failed: '失败',
      interrupted: '已中断',
    } as Record<BatchFileStatus, string>
  )[status]
}

export function ignoredReasonLabel(reason: EtlIgnoredSourceFile['reason'], maxFileBytes = ETL_MAX_FILE_BYTES) {
  return (
    {
      unsupported: '文件类型不支持',
      too_large: `单文件超过 ${formatEtlBytes(maxFileBytes)}`,
      duplicate: '重复文件',
    } as Record<EtlIgnoredSourceFile['reason'], string>
  )[reason]
}

export function useEtlFolderBatch(options: EtlFolderBatchOptions) {
  const selectedFiles = ref<EtlBatchFile[]>([])
  const ignoredFiles = ref<EtlIgnoredSourceFile[]>([])
  const selectionFolderName = ref('')
  const batchId = ref('')
  const fileInput = ref<HTMLInputElement | null>(null)
  const folderInput = ref<HTMLInputElement | null>(null)
  let batchPollTimer: ReturnType<typeof setTimeout> | null = null

  const maxFileBytes = computed(() => options.capabilities.value?.limits.max_file_bytes || ETL_MAX_FILE_BYTES)
  const selectedTotalBytes = computed(() => selectedFiles.value.reduce((sum, item) => sum + item.file.size, 0))
  const knowledgeOnlyFiles = computed(() => selectedFiles.value.filter((item) => ['.doc', '.docx', '.ppt', '.pptx'].includes(item.suffix)))
  const incompatibleFiles = computed(() => (['auto', 'knowledge'].includes(options.targetType.value) ? [] : knowledgeOnlyFiles.value))
  function terminalStatuses() {
    return options.autoWriteEnabled.value ? WRITE_TERMINAL_STATUSES : PARSE_DONE_STATUSES
  }

  const batchFinishedCount = computed(() => selectedFiles.value.filter((item) => terminalStatuses().has(item.status)).length)
  const batchFailedCount = computed(() => selectedFiles.value.filter((item) => item.status === 'failed').length)
  const batchSubmittedCount = computed(
    () => selectedFiles.value.filter((item) => !['waiting', 'uploading', 'creating'].includes(item.status)).length,
  )
  const batchProgress = computed(() => {
    if (!selectedFiles.value.length) return 0
    const total = selectedFiles.value.reduce((sum, item) => sum + item.progress, 0)
    return Math.round(total / selectedFiles.value.length)
  })
  const selectionHeadline = computed(() => {
    if (!selectedFiles.value.length) return '拖入文件，或选择文件 / 整个文件夹'
    if (selectionFolderName.value) {
      return `${selectionFolderName.value} · ${selectedFiles.value.length} 个可处理文件`
    }
    return `${selectedFiles.value.length} 个文件 · ${formatEtlBytes(selectedTotalBytes.value)}`
  })
  const startButtonText = computed(() => {
    if (options.busy.value) {
      return `正在提交 ${batchSubmittedCount.value}/${selectedFiles.value.length}…`
    }
    if (options.autoWriteEnabled.value) {
      if (selectedFiles.value.length > 1) {
        return `批量上传并写入 ${selectedFiles.value.length} 个文件`
      }
      return '上传并写入数据库'
    }
    if (selectedFiles.value.length > 1) {
      return `批量上传并解析 ${selectedFiles.value.length} 个文件`
    }
    return '上传并解析'
  })

  function applyFileSelection(files: Iterable<File>) {
    const selection = selectEtlSourceFiles(files, maxFileBytes.value)
    selectedFiles.value = selection.accepted.map((item) => ({
      ...item,
      status: 'waiting',
      progress: 0,
    }))
    ignoredFiles.value = selection.ignored
    selectionFolderName.value = selection.folderName
    batchId.value = selectedFiles.value.length ? newBatchId() : ''
    if (knowledgeOnlyFiles.value.length === selectedFiles.value.length && selectedFiles.value.length) {
      options.targetType.value = 'knowledge'
    }
  }

  function onFileChange(event: Event) {
    applyFileSelection(Array.from((event.target as HTMLInputElement).files || []))
  }

  function onFolderChange(event: Event) {
    applyFileSelection(Array.from((event.target as HTMLInputElement).files || []))
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    if (options.busy.value || !event.dataTransfer?.files?.length) return
    applyFileSelection(Array.from(event.dataTransfer.files))
  }

  function clearSelection() {
    selectedFiles.value = []
    ignoredFiles.value = []
    selectionFolderName.value = ''
    batchId.value = ''
    if (fileInput.value) fileInput.value.value = ''
    if (folderInput.value) folderInput.value.value = ''
  }

  function removeSelectedFile(id: string) {
    selectedFiles.value = selectedFiles.value.filter((item) => item.id !== id)
    if (!selectedFiles.value.length) clearSelection()
  }

  function mergeBatchRuns(latest: EtlRun[]) {
    const byId = new Map(latest.map((run) => [run.id, run]))
    for (const item of selectedFiles.value) {
      if (!item.runId) continue
      const run = byId.get(item.runId)
      if (!run) continue
      item.status = run.status as BatchFileStatus
      item.progress = terminalStatuses().has(item.status) ? 100 : Math.max(item.progress, run.progress)
      item.message = run.error?.message || ''
    }
    options.runs.value = [...latest, ...options.runs.value.filter((run) => !byId.has(run.id))]
    if (options.currentRun.value) {
      options.currentRun.value = byId.get(options.currentRun.value.id) || options.currentRun.value
    }
  }

  function scheduleBatchPoll() {
    if (batchPollTimer) clearTimeout(batchPollTimer)
    const pending = selectedFiles.value.some((item) => item.runId && !terminalStatuses().has(item.status))
    if (!pending || !batchId.value) return
    batchPollTimer = setTimeout(async () => {
      try {
        const limit = Math.min(500, Math.max(50, selectedFiles.value.length))
        const latest = await etlApi.runs(limit, batchId.value)
        mergeBatchRuns(latest)
        if (options.autoWriteEnabled.value) {
          for (const run of latest) {
            if (run.status === 'preview_ready') await options.tryAutoWrite(run)
          }
        }
      } catch (error) {
        options.pageError.value = error instanceof Error ? error.message : '读取文件夹写入进度失败'
      }
      scheduleBatchPoll()
    }, 1500)
  }

  async function startPreview() {
    if (!selectedFiles.value.length || incompatibleFiles.value.length) return
    options.busy.value = true
    options.pageError.value = ''
    const createdRuns: EtlRun[] = []
    try {
      const queue = selectedFiles.value.filter((item) => ['waiting', 'failed'].includes(item.status))
      let cursor = 0
      async function worker() {
        while (cursor < queue.length) {
          const item = queue[cursor++]
          item.status = 'uploading'
          item.progress = 10
          item.message = ''
          try {
            const upload = await etlApi.upload(item.file, {
              batchId: batchId.value,
              relativePath: item.relativePath,
            })
            item.status = 'creating'
            item.progress = 35
            const run = await etlApi.preview({
              upload_id: upload.upload_id,
              target_type: options.targetType.value,
              template_id: options.templateId.value || undefined,
              compatibility_preset_id: options.compatibilityPresetId.value || undefined,
              target_config_id: options.targetConfigId.value || undefined,
            })
            item.runId = run.id
            item.status = run.status as BatchFileStatus
            item.progress = Math.max(40, run.progress)
            if (options.autoWriteEnabled.value) options.markAutoWrite(run.id)
            createdRuns.push(run)
          } catch (error) {
            item.status = 'failed'
            item.progress = 100
            item.message = error instanceof Error ? error.message : '创建导入任务失败'
          }
        }
      }
      const workers = Array.from({ length: Math.min(3, Math.max(1, queue.length)) }, () => worker())
      await Promise.all(workers)
      if (createdRuns.length) {
        options.runs.value = [
          ...createdRuns,
          ...options.runs.value.filter((item) => !createdRuns.some((created) => created.id === item.id)),
        ]
        options.currentRun.value = createdRuns[0]
        if (selectedFiles.value.length === 1 && options.targetType.value === 'auto') {
          options.targetType.value = createdRuns[0].target_type
        }
        options.syncDraft()
        await options.router.replace({
          path: '/business-docking',
          query: { run_id: createdRuns[0].id },
        })
        if (selectedFiles.value.length === 1) {
          // Small workbooks may finish parse before the create response returns.
          // Auto-write continues into execute; otherwise surface the review tab.
          if (createdRuns[0].status === 'preview_ready' && options.autoWriteEnabled.value) {
            await options.tryAutoWrite(createdRuns[0])
          } else {
            options.activeTab.value = tabForRunStatus(createdRuns[0].status)
            if (createdRuns[0].status === 'preview_ready') await options.loadRows()
            options.schedulePoll()
          }
        } else {
          scheduleBatchPoll()
        }
      }
      if (batchFailedCount.value) {
        options.pageError.value = `${batchFailedCount.value} 个文件提交失败；可在文件清单中查看原因并重试。`
      }
    } finally {
      options.busy.value = false
    }
  }

  async function openBatchRun(item: EtlBatchFile) {
    if (!item.runId) return
    options.currentRun.value = await etlApi.run(item.runId)
    options.syncDraft()
    options.activeTab.value = tabForRunStatus(options.currentRun.value.status)
    if (options.currentRun.value.status === 'preview_ready') await options.loadRows()
    await options.router.replace({
      path: '/business-docking',
      query: { run_id: item.runId },
    })
    options.schedulePoll()
  }

  onBeforeUnmount(() => {
    if (batchPollTimer) clearTimeout(batchPollTimer)
  })

  return {
    selectedFiles,
    ignoredFiles,
    selectionFolderName,
    fileInput,
    folderInput,
    maxFileBytes,
    selectedTotalBytes,
    incompatibleFiles,
    batchFinishedCount,
    batchFailedCount,
    batchProgress,
    selectionHeadline,
    startButtonText,
    onFileChange,
    onFolderChange,
    onDrop,
    clearSelection,
    removeSelectedFile,
    startPreview,
    openBatchRun,
  }
}
