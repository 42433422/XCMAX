// 报告预览与产出下载 IO：对象 URL 生命周期、iframe 滚动定位与文件下载。
import type { ComputedRef, Ref } from 'vue'
import { nextTick } from 'vue'
import { api } from '../../api'
import type { EmployeeOutputDownload } from '../../utils/tabularReadEmployees'
import type { PipelineStepId, PipelineStepStatus } from './employeeExamTypes'

type ReportDeps = {
  htmlReportDownload: ComputedRef<EmployeeOutputDownload | undefined>
  htmlReportPreviewUrl: Ref<string>
  downloadingKey: Ref<string>
  htmlPreviewLoading: Ref<boolean>
  reportHeroRef: Ref<HTMLElement | null>
  runError: Ref<string>
  pipelineStatuses: Ref<Record<PipelineStepId, PipelineStepStatus>>
  setPipelineStep: (id: PipelineStepId, status: PipelineStepStatus, message?: string) => void
}

export function useEmployeeExamReport(deps: ReportDeps) {
  const { htmlReportDownload, htmlReportPreviewUrl, downloadingKey, htmlPreviewLoading, reportHeroRef, runError } = deps

  function revokeHtmlPreview() {
    if (htmlReportPreviewUrl.value) {
      URL.revokeObjectURL(htmlReportPreviewUrl.value)
      htmlReportPreviewUrl.value = ''
    }
  }

  async function previewHtmlReport() {
    const d = htmlReportDownload.value
    if (!d) return
    if (deps.pipelineStatuses.value.preview !== 'skipped') {
      deps.setPipelineStep('preview', 'active', '加载 HTML 预览…')
    }
    htmlPreviewLoading.value = true
    try {
      const blob = await api.employeeOutputDownload(d.jobId, d.filename)
      revokeHtmlPreview()
      htmlReportPreviewUrl.value = URL.createObjectURL(blob)
      deps.setPipelineStep('preview', 'done', '报告已就绪')
      await nextTick()
      reportHeroRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    } catch (e: unknown) {
      const msg = `预览失败：${(e as Error)?.message || String(e)}`
      runError.value = msg
      deps.setPipelineStep('preview', 'error', msg)
    } finally {
      htmlPreviewLoading.value = false
    }
  }

  async function downloadHtmlReport() {
    const d = htmlReportDownload.value
    if (!d) return
    await downloadOutput(d)
  }

  function openHtmlReportInNewTab() {
    if (htmlReportPreviewUrl.value) {
      window.open(htmlReportPreviewUrl.value, '_blank', 'noopener,noreferrer')
    }
  }

  async function downloadOutput(d: EmployeeOutputDownload) {
    const key = `${d.jobId}:${d.filename}`
    downloadingKey.value = key
    try {
      const blob = await api.employeeOutputDownload(d.jobId, d.filename)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = d.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e: unknown) {
      runError.value = `下载失败：${(e as Error)?.message || String(e)}`
    } finally {
      downloadingKey.value = ''
    }
  }

  return {
    revokeHtmlPreview,
    previewHtmlReport,
    downloadHtmlReport,
    openHtmlReportInNewTab,
    downloadOutput,
  }
}
