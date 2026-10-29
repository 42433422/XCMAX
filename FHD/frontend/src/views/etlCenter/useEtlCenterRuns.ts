/**
 * 数据对接中心运行生命周期（拆分自 views/EtlCenterView.vue，行为保持一致）：
 * 引导加载、轮询、审核确认、逐行/批量动作、历史选择、重试与撤销。
 */
import type { ComputedRef } from 'vue'
import type { Router } from 'vue-router'
import { etlApi, type EtlRun, type EtlRunRow } from '@/api/etl'
import { tabForRunStatus } from '@/utils/etlRunView'
import type { EtlCenterState } from './etlCenterState'
import { createEtlProductInvalidation } from '@/utils/etlProductInvalidation'
import { createTargetLabel, resultNeedsVerification, targetOperation } from './etlCenterShared'

export interface EtlCenterRunsDeps {
  state: EtlCenterState
  route: { query: Record<string, unknown> }
  router: Pick<Router, 'replace'>
  canExecute: ComputedRef<boolean>
  canRollback: ComputedRef<boolean>
  shipmentTemplateCandidates: ComputedRef<Array<Record<string, unknown>>>
  bulkNewRows: ComputedRef<EtlRunRow[]>
}

export function createEtlCenterRuns({ state, route, router, canExecute, canRollback, shipmentTemplateCandidates, bulkNewRows }: EtlCenterRunsDeps) {
  const productChanges = createEtlProductInvalidation()
  const readRun = (id: string) => productChanges.read(() => etlApi.run(id))
  const readRuns = () => productChanges.readMany(() => etlApi.runs())
  const {
    activeTab,
    busy,
    pageError,
    runs,
    currentRun,
    targetType,
    runRows,
    rowPage,
    rowTotal,
    rowActionFilter,
    sourceSheetFilter,
    sourceRowFilter,
    sourceSheetInput,
    sourceRowInput,
    requestedRowPage,
    rowsLoading,
    reviewedPreviewRevision,
    validRowsOnly,
    editableMappings,
    mappingUiTransform,
    mappingUiTransformJson,
    allowedUpdateFields,
    ocrConfirmed,
    hasOcrRows,
    selectedShipmentTemplateRegionId,
    customerProductPreviewMessage,
    pollTimer,
  } = state
  let selectionGeneration = 0
  let rowReadGeneration = 0
  let runReadGeneration = 0
  let historyGeneration = 0
  let bootstrapGeneration = 0
  let pollGeneration = 0

  async function bootstrap() {
    const request = ++bootstrapGeneration
    const historyRequest = ++historyGeneration
    const selection = selectionGeneration
    const isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    pageError.value = ''
    try {
      const [caps, templateRows, history, configs] = await Promise.all([
        etlApi.capabilities(),
        etlApi.templates(),
        readRuns(),
        etlApi.targetConfigs(),
      ])
      if (request !== bootstrapGeneration || !isCurrent()) return
      state.capabilities.value = caps
      state.templates.value = templateRows
      if (historyRequest === historyGeneration) runs.value = history
      state.targetConfigs.value = configs
      if (targetType.value !== 'auto' && !caps.targets.some((item) => item.type === targetType.value)) {
        targetType.value = 'auto'
      }
      const requestedRun = String(route.query.run_id || '')
      if (requestedRun && selection === selectionGeneration) await selectRun({ id: requestedRun })
    } catch (error) {
      if (request === bootstrapGeneration && isCurrent()) pageError.value = error instanceof Error ? error.message : '数据对接中心加载失败'
    } finally {
      finishBusy()
    }
  }

  function schedulePoll() {
    const polling = ++pollGeneration
    if (pollTimer.value) clearTimeout(pollTimer.value)
    pollTimer.value = null
    const run = currentRun.value
    const isCurrent = state.captureReadContext()
    if (!isCurrent() || !run || !['queued', 'previewing', 'executing'].includes(run.status)) return
    pollTimer.value = setTimeout(async () => {
      const request = ++runReadGeneration
      try {
        if (polling !== pollGeneration || !isCurrent()) return
        const latest = await readRun(run.id)
        if (request !== runReadGeneration || polling !== pollGeneration || !isCurrent()) return
        currentRun.value = latest
        syncDraft()
        const ownsUpdatedRun = state.captureReadContext()
        if (currentRun.value.status === 'preview_ready') {
          activeTab.value = 'preview'
          await loadRows()
          if (ownsUpdatedRun()) await refreshRuns()
        } else if (currentRun.value.status === 'completed') {
          activeTab.value = 'history'
          await refreshRuns()
        }
      } catch (error) {
        if (request === runReadGeneration && polling === pollGeneration && isCurrent()) pageError.value = error instanceof Error ? error.message : '读取运行进度失败'
      } finally {
        if (polling === pollGeneration) schedulePoll()
      }
    }, 1200)
  }

  function syncDraft() {
    if (!currentRun.value) return
    const candidateIds = shipmentTemplateCandidates.value.map((candidate) => String(candidate.source_region_id || '').trim()).filter(Boolean)
    if (!candidateIds.includes(selectedShipmentTemplateRegionId.value)) {
      selectedShipmentTemplateRegionId.value = candidateIds[0] || ''
    }
    editableMappings.value = (currentRun.value.draft.field_mappings || []).map((item) => ({
      ...item,
      transforms: [...(item.transforms || [])],
    }))
    for (const [index, mapping] of editableMappings.value.entries()) {
      const firstOp = String(mapping.transforms?.[0]?.op || '')
      const simple = mapping.transforms.length <= 1 && Object.keys(mapping.transforms[0] || {}).every(key => key === 'op')
      mappingUiTransform[String(index)] = simple && ['', 'trim', 'number', 'date'].includes(firstOp) ? firstOp : 'custom'
      mappingUiTransformJson[String(index)] = JSON.stringify(mapping.transforms || [])
    }
    allowedUpdateFields.value = [...(currentRun.value.draft.allowed_update_fields || [])]
    ocrConfirmed.value = Boolean(currentRun.value.draft.ocr_confirmed)
  }

  async function loadRows() {
    const request = ++rowReadGeneration
    const contextCurrent = state.captureReadContext()
    reviewedPreviewRevision.value = null
    runRows.value = []
    hasOcrRows.value = false
    if (!currentRun.value || currentRun.value.total_rows === 0) {
      rowsLoading.value = false
      rowTotal.value = 0
      return
    }
    const run = currentRun.value
    const revision = run.preview_revision
    const page = rowPage.value, action = rowActionFilter.value, sheet = sourceSheetFilter.value, sourceRow = sourceRowFilter.value
    const isCurrent = () => request === rowReadGeneration && contextCurrent() && currentRun.value?.id === run.id && currentRun.value.preview_revision === revision &&
      rowPage.value === page && rowActionFilter.value === action && sourceSheetFilter.value === sheet && sourceRowFilter.value === sourceRow
    rowsLoading.value = true
    try {
      const result = sheet || sourceRow
        ? await etlApi.rows(run.id, page, 50, action, { sheet, row: sourceRow || undefined })
        : await etlApi.rows(run.id, page, 50, action)
      if (!isCurrent()) return
      if (result.preview_revision !== revision || (result.page != null && result.page !== page)) {
        pageError.value = '预演内容已变化，请重新读取任务后核对。'
        return
      }
      rowTotal.value = result.total
      const lastPage = Math.max(1, Math.ceil(result.total / 50))
      if (page > lastPage) {
        rowPage.value = lastPage
        await loadRows()
        return
      }
      requestedRowPage.value = page
      runRows.value = result.items
      hasOcrRows.value = result.items.some((row) => row.provenance.ocr === true)
      if (run.status === 'preview_ready' && revision && result.items.length && page > 0 && (page - 1) * 50 < result.total) reviewedPreviewRevision.value = revision
    } catch (error) {
      if (isCurrent()) {
        runRows.value = []
        pageError.value = error instanceof Error ? error.message : '读取核对数据失败，请重试。'
      }
    } finally {
      if (request === rowReadGeneration) rowsLoading.value = false
    }
  }

  async function goToRowPage(page = Number(requestedRowPage.value)) {
    const lastPage = Math.max(1, Math.ceil(rowTotal.value / 50))
    if (!Number.isSafeInteger(page) || page < 1 || page > lastPage) {
      pageError.value = `请输入 1 至 ${lastPage} 之间的页码。`
      return
    }
    pageError.value = ''
    rowPage.value = page
    await loadRows()
  }

  async function locateSourceRow(clear = false) {
    if (clear) {
      sourceSheetInput.value = ''
      sourceRowInput.value = ''
    }
    const row = sourceRowInput.value
    if (row !== '' && (!Number.isSafeInteger(row) || row < 1)) {
      pageError.value = '来源行号须为大于 0 的整数。'
      return
    }
    sourceSheetFilter.value = sourceSheetInput.value.trim()
    sourceRowFilter.value = row
    rowPage.value = 1
    pageError.value = ''
    await loadRows()
  }

  async function setRowActionFilter(action: string) {
    if (action === rowActionFilter.value) return
    rowActionFilter.value = action
    rowPage.value = 1
    await loadRows()
  }

  function onRowActionFilterChange(event: Event) {
    void setRowActionFilter((event.target as HTMLSelectElement).value)
  }

  async function overrideRow(row: EtlRunRow, event: Event) {
    const run = currentRun.value
    if (busy.value || !run) return
    const action = (event.target as HTMLSelectElement).value
    let isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    pageError.value = ''
    try {
      const updated = await etlApi.patchDraft(run.id, {
        row_overrides: { [String(row.id)]: action },
      })
      if (!isCurrent()) return
      currentRun.value = updated
      isCurrent = state.captureReadContext()
      await loadRows()
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '逐行动作保存失败'
    } finally {
      finishBusy()
    }
  }

  async function bulkOverride(action: 'new' | 'skip') {
    const run = currentRun.value
    if (busy.value || !run) return
    const candidates = action === 'new' ? bulkNewRows.value : runRows.value.filter((row) => row.validation_issues.length === 0)
    if (!candidates.length) return
    let isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    pageError.value = ''
    try {
      const updated = await etlApi.patchDraft(run.id, {
        row_overrides: Object.fromEntries(candidates.map((row) => [String(row.id), action])),
      })
      if (!isCurrent()) return
      currentRun.value = updated
      isCurrent = state.captureReadContext()
      await loadRows()
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '批量动作保存失败'
    } finally {
      finishBusy()
    }
  }

  async function executeCurrentRun() {
    const run = currentRun.value
    const revision = run?.preview_revision
    if (busy.value || !run || !canExecute.value || !revision || reviewedPreviewRevision.value !== revision) return
    const onlyValid = validRowsOnly.value
    const operation = targetOperation(run.target_type)
    const config = state.targetConfigs.value.find(item => item.id === run.draft.target_config_id)
    const target = config ? `${config.name}（${config.endpoint_url}）` : createTargetLabel(state.capabilities)(run.target_type)
    const scope = onlyValid ? `仅处理正确行，排除 ${run.summary.error} 行错误。` : '发现错误时停止处理。'
    const irreversible = run.reversible ? '' : '\n此目标不支持撤销，请确认目标与内容。'
    if (!window.confirm(`确认${operation.action}：“${run.file_name}”？\n目标：${target}\n新增 ${run.summary.new} 行、更新 ${run.summary.update} 行、跳过 ${run.summary.skip} 行。\n${scope}${irreversible}`)) return
    const finishBusy = state.beginBusy()
    pageError.value = ''
    let isCurrent = state.captureReadContext()
    try {
      const executed = await productChanges.mutate(run, () => etlApi.execute(run.id, revision, onlyValid))
      if (!isCurrent()) return
      currentRun.value = executed
      activeTab.value = 'history'
      isCurrent = state.captureReadContext()
      schedulePoll()
      await refreshRuns()
    } catch (error) {
      if (!isCurrent()) return
      pageError.value = error instanceof Error ? error.message : '执行失败'
      reviewedPreviewRevision.value = null
      const request = ++runReadGeneration
      const latest = await readRun(run.id).catch(() => run)
      if (request !== runReadGeneration || !isCurrent()) return
      currentRun.value = latest
      syncDraft()
      if (currentRun.value.status === 'preview_ready') {
        activeTab.value = 'preview'
        await loadRows().catch(() => undefined)
      }
    } finally {
      finishBusy()
    }
  }

  async function refreshRuns() {
    const request = ++historyGeneration
    const runRequest = ++runReadGeneration
    const isCurrent = state.captureReadContext()
    try {
      const history = await readRuns()
      if (request !== historyGeneration || !isCurrent()) return
      runs.value = history
      if (currentRun.value && runRequest === runReadGeneration) {
        const latest = history.find((item) => item.id === currentRun.value?.id)
        if (latest) currentRun.value = latest
      }
    } catch (error) {
      if (request === historyGeneration && isCurrent()) pageError.value = error instanceof Error ? error.message : '读取运行历史失败'
    }
  }

  async function selectRun(run: Pick<EtlRun, 'id'>) {
    const selection = ++selectionGeneration
    runReadGeneration += 1
    pageError.value = ''
    customerProductPreviewMessage.value = ''
    currentRun.value = null
    rowPage.value = 1
    rowActionFilter.value = ''
    schedulePoll()
    let isCurrent = state.captureReadContext()
    try {
      const latest = await readRun(run.id)
      if (selection !== selectionGeneration || !isCurrent()) return
      currentRun.value = latest
      syncDraft()
      activeTab.value = tabForRunStatus(latest.status)
      isCurrent = state.captureReadContext()
      await router.replace({ path: '/business-docking', query: { run_id: run.id } })
      if (selection !== selectionGeneration || !isCurrent()) return
      if (latest.status === 'preview_ready') await loadRows()
      if (selection === selectionGeneration && isCurrent()) schedulePoll()
    } catch (error) {
      if (selection === selectionGeneration && isCurrent()) pageError.value = error instanceof Error ? error.message : '读取运行详情失败'
    }
  }

  async function retryRun() {
    const run = currentRun.value
    if (busy.value || !run || run.rollback_status || resultNeedsVerification(run) || !['failed', 'interrupted'].includes(run.status)) return
    const isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    pageError.value = ''
    try {
      const retried = await etlApi.retry(run.id)
      if (!isCurrent()) return
      currentRun.value = retried
      activeTab.value = 'upload'
      schedulePoll()
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '重试失败'
    } finally {
      finishBusy()
    }
  }

  async function replayRun() {
    const run = currentRun.value
    if (!run || busy.value) return
    let isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    pageError.value = ''
    try {
      const replayed = await etlApi.replay(run.id)
      if (!isCurrent()) return
      currentRun.value = replayed
      validRowsOnly.value = false
      rowPage.value = 1
      rowActionFilter.value = ''
      customerProductPreviewMessage.value = ''
      syncDraft()
      activeTab.value = 'preview'
      isCurrent = state.captureReadContext()
      await router.replace({ path: '/business-docking', query: { run_id: replayed.id } })
      if (!isCurrent()) return
      await loadRows()
      if (!isCurrent()) return
      schedulePoll()
      await refreshRuns()
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '重新处理失败'
    } finally {
      finishBusy()
    }
  }

  async function rollbackRun() {
    const run = currentRun.value
    if (busy.value || !run) return
    if (resultNeedsVerification(run)) {
      pageError.value = '上次操作结果尚未确认，请先核对实际数据并联系管理员处理。'
      return
    }
    if (!canRollback.value) {
      pageError.value = '当前账号没有撤销权限，请联系管理员授权后重试。'
      return
    }
    if (!window.confirm('确认撤销本次内部写入？更新将恢复前镜像，新增记录将被删除。')) return
    let isCurrent = state.captureReadContext()
    const finishBusy = state.beginBusy()
    pageError.value = ''
    try {
      const rolledBack = await productChanges.mutate(run, () => etlApi.rollback(run.id))
      if (!isCurrent()) return
      currentRun.value = rolledBack
      isCurrent = state.captureReadContext()
      await refreshRuns()
    } catch (error) {
      if (isCurrent()) pageError.value = error instanceof Error ? error.message : '撤销失败'
    } finally {
      finishBusy()
    }
  }

  return {
    bootstrap,
    schedulePoll,
    syncDraft,
    loadRows,
    goToRowPage,
    locateSourceRow,
    setRowActionFilter,
    onRowActionFilterChange,
    overrideRow,
    bulkOverride,
    executeCurrentRun,
    refreshRuns,
    selectRun,
    retryRun,
    replayRun,
    rollbackRun,
  }
}

export type EtlCenterRuns = ReturnType<typeof createEtlCenterRuns>
