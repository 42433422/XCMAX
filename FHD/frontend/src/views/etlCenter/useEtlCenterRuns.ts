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

  async function bootstrap() {
    busy.value = true
    pageError.value = ''
    try {
      const [caps, templateRows, history, configs] = await Promise.all([
        etlApi.capabilities(),
        etlApi.templates(),
        readRuns(),
        etlApi.targetConfigs(),
      ])
      state.capabilities.value = caps
      state.templates.value = templateRows
      runs.value = history
      state.targetConfigs.value = configs
      if (targetType.value !== 'auto' && !caps.targets.some((item) => item.type === targetType.value)) {
        targetType.value = 'auto'
      }
      const requestedRun = String(route.query.run_id || '')
      if (requestedRun) {
        currentRun.value = await readRun(requestedRun)
        syncDraft()
        activeTab.value = tabForRunStatus(currentRun.value.status)
        if (currentRun.value.status === 'preview_ready') await loadRows()
        schedulePoll()
      }
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '数据对接中心加载失败'
    } finally {
      busy.value = false
    }
  }

  function schedulePoll() {
    if (pollTimer.value) clearTimeout(pollTimer.value)
    if (!currentRun.value || !['queued', 'previewing', 'executing'].includes(currentRun.value.status)) return
    pollTimer.value = setTimeout(async () => {
      if (!currentRun.value) return
      try {
        currentRun.value = await readRun(currentRun.value.id)
        syncDraft()
        if (currentRun.value.status === 'preview_ready') {
          activeTab.value = 'preview'
          await loadRows()
          await refreshRuns()
        } else if (currentRun.value.status === 'completed') {
          activeTab.value = 'history'
          await refreshRuns()
        }
      } catch (error) {
        pageError.value = error instanceof Error ? error.message : '读取运行进度失败'
      }
      schedulePoll()
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

  let rowRequest = 0
  async function loadRows() {
    const request = ++rowRequest
    reviewedPreviewRevision.value = null
    if (!currentRun.value || currentRun.value.total_rows === 0) {
      rowsLoading.value = false
      runRows.value = []
      rowTotal.value = 0
      return
    }
    const run = currentRun.value
    const revision = run.preview_revision
    const page = rowPage.value, action = rowActionFilter.value, sheet = sourceSheetFilter.value, sourceRow = sourceRowFilter.value
    const isCurrent = () => request === rowRequest && currentRun.value?.id === run.id && currentRun.value.preview_revision === revision &&
      rowPage.value === page && rowActionFilter.value === action && sourceSheetFilter.value === sheet && sourceRowFilter.value === sourceRow
    rowsLoading.value = true
    try {
      const result = sheet || sourceRow
        ? await etlApi.rows(run.id, page, 50, action, { sheet, row: sourceRow || undefined })
        : await etlApi.rows(run.id, page, 50, action)
      if (!isCurrent()) return
      if (result.preview_revision !== revision) {
        runRows.value = []
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
      if (run.status === 'preview_ready' && revision && result.items.length) reviewedPreviewRevision.value = revision
    } catch (error) {
      if (isCurrent()) {
        runRows.value = []
        pageError.value = error instanceof Error ? error.message : '读取核对数据失败，请重试。'
      }
    } finally {
      if (request === rowRequest) rowsLoading.value = false
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
    if (!currentRun.value) return
    const action = (event.target as HTMLSelectElement).value
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
        row_overrides: { [String(row.id)]: action },
      })
      await loadRows()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '逐行动作保存失败'
    } finally {
      busy.value = false
    }
  }

  async function bulkOverride(action: 'new' | 'skip') {
    if (!currentRun.value) return
    const candidates = action === 'new' ? bulkNewRows.value : runRows.value.filter((row) => row.validation_issues.length === 0)
    if (!candidates.length) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
        row_overrides: Object.fromEntries(candidates.map((row) => [String(row.id), action])),
      })
      await loadRows()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '批量动作保存失败'
    } finally {
      busy.value = false
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
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await productChanges.mutate(run, () => etlApi.execute(run.id, revision, onlyValid))
      activeTab.value = 'history'
      await refreshRuns()
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '执行失败'
      reviewedPreviewRevision.value = null
      currentRun.value = await readRun(run.id).catch(() => run)
      syncDraft()
      if (currentRun.value.status === 'preview_ready') {
        activeTab.value = 'preview'
        await loadRows().catch(() => undefined)
      }
    } finally {
      busy.value = false
    }
  }

  async function refreshRuns() {
    runs.value = await readRuns()
    if (currentRun.value) {
      const latest = runs.value.find((item) => item.id === currentRun.value?.id)
      if (latest) currentRun.value = latest
    }
  }

  async function selectRun(run: EtlRun) {
    pageError.value = ''
    customerProductPreviewMessage.value = ''
    currentRun.value = await readRun(run.id)
    syncDraft()
    activeTab.value = tabForRunStatus(currentRun.value.status)
    if (currentRun.value.status === 'preview_ready') await loadRows()
    await router.replace({ path: '/business-docking', query: { run_id: run.id } })
    schedulePoll()
  }

  async function retryRun() {
    if (!currentRun.value || busy.value || currentRun.value.rollback_status || resultNeedsVerification(currentRun.value) ||
      !['failed', 'interrupted'].includes(currentRun.value.status)) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await etlApi.retry(currentRun.value.id)
      activeTab.value = 'upload'
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '重试失败'
    } finally {
      busy.value = false
    }
  }

  async function replayRun() {
    if (!currentRun.value || busy.value) return
    busy.value = true
    pageError.value = ''
    try {
      const replayed = await etlApi.replay(currentRun.value.id)
      currentRun.value = replayed
      validRowsOnly.value = false
      rowPage.value = 1
      rowActionFilter.value = ''
      customerProductPreviewMessage.value = ''
      syncDraft()
      activeTab.value = 'preview'
      await loadRows()
      await refreshRuns()
      await router.replace({ path: '/business-docking', query: { run_id: replayed.id } })
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '重新处理失败'
    } finally {
      busy.value = false
    }
  }

  async function rollbackRun() {
    if (!currentRun.value) return
    if (resultNeedsVerification(currentRun.value)) {
      pageError.value = '上次操作结果尚未确认，请先核对实际数据并联系管理员处理。'
      return
    }
    if (!canRollback.value) {
      pageError.value = '当前账号没有撤销权限，请联系管理员授权后重试。'
      return
    }
    if (!window.confirm('确认撤销本次内部写入？更新将恢复前镜像，新增记录将被删除。')) return
    busy.value = true
    pageError.value = ''
    try {
      currentRun.value = await productChanges.mutate(currentRun.value, () => etlApi.rollback(currentRun.value!.id))
      await refreshRuns()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '撤销失败'
    } finally {
      busy.value = false
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
