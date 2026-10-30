<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, type CSSProperties } from 'vue'
import { captureAuthSession, getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import templatePreviewApi from '@/api/templatePreview'

type Cell = { sheet: string; cell: string; value: string; kind: string; reason: string }
type Candidate = { id: string; label: string; explanation: string; clear: { sheet: string; cell: string }[] }
type Proposal = { version: string; parent_version: string | null; candidates: Candidate[]; result_previews?: { candidate_id: string; sha256: string; layout: Layout[]; layout_truncated: boolean }[]; evidence: unknown[]; model: { status: string; cells_sent?: number; cells_total?: number; truncated?: boolean; values_truncated?: boolean; input_messages?: unknown[]; input_summary?: unknown } }
type LayoutCell = { cell: string; value: string; formula: boolean; rowspan: number; colspan: number; bold: boolean; italic: boolean; font_size: number; font_color: string; fill: string; align: string }
type Layout = { sheet: string; widths: number[]; rows: { height: number; cells: LayoutCell[] }[]; truncated: boolean }
type Review = { review_id: string; sha256: string; cells: Cell[]; sheets: string[]; model: string; proposal: Proposal; versions?: Proposal[]; layout?: Layout[]; layout_truncated?: boolean; selected_region?: { selection_basis?: string; print_area_mode?: string; source_print_areas?: { sheet: string; value: string }[]; derived_print_area?: string | null } | null }
type ClassificationRegion = { splitDraft?: string; value_extent?: string | null; suggested_labels?: string[]; context_warning?: string; reason?: string; continuation_context?: { parent_range: string; parent_header_row: number; header_row: number; matched_columns: number[] } | null; range: string; original_range?: string; labels: string[]; label_source?: string; range_source?: string; modified?: boolean; checked_cells: number; parent_heading: string; dependency_status: string; needs_confirmation: boolean; header_cells: { cell: string; value: string }[]; merged_ranges: string[]; dependencies?: { sheet: string; cell: string }[]; possible_shared_context: { cell: string; kind: string }[]; evidence: { label: string; cell: string; matched: string }[] }
type ClassificationSheet = { sheet: string; labels: string[]; checked_cells: number; evidence: { label: string; cell: string; matched: string }[]; regions: ClassificationRegion[] }
type FragmentLinks = { items: { sheet: string; first: string; second: string; shared_dependencies: { sheet: string; cell: string }[]; repeated_header_observed: boolean; model_group_suggested?: boolean; status: string; selected?: boolean }[]; omitted: number }
type LogicalDocument = { logical_document_id: string; fragments: { sheet: string; range: string }[]; status: string }
type SuggestedDocument = { document_id: string; fragments: { sheet: string; range: string }[]; status: string }
type AutoSlice = { index: number; basis: string; confirmed: boolean; sha256: string; filename: string; fragments: { sheet: string; range: string }[] }
type Checkpoint = { phase: 'ready' | 'paused' | 'inflight'; version: string; completed: number; total: number; max_calls: number; calls_in_round?: number; remaining_in_round?: number; message: string }
type Classification = { template_write_state?: string; independent_confirmed?: boolean; confirmed_document_count?: number | null; document_count_status?: string; suggested_documents?: SuggestedDocument[]; suggested_document_count?: number | null; read_only_print_areas?: { sheet: string; value: string }[]; logical_documents?: LogicalDocument[]; fragment_links?: FragmentLinks; checkpoint?: Checkpoint | null; name: string; status: string; sha256?: string; message?: string; classification_id?: string; version?: string; confirmed?: boolean; model_status?: string; budget?: { calls: number; max_calls: number; unread: number }; input_messages?: unknown[]; input_summaries?: unknown[]; coverage?: { sheet: string; total: number; sent: number; unread: string[]; unassigned: string[]; model_unassigned?: string[]; value_truncated: string[]; deferred_large_values?: string[]; deferred_oversized_rows?: string[]; merged_sent: number; merged_omitted: number }[]; sheets: ClassificationSheet[] }
type RecentClassification = { archive_version_id?: string | null; template_write_state?: string; checkpoint?: Checkpoint | null; classification_id: string; name: string; sha256: string; latest: { version: string; confirmed: boolean; model_status: string; sheets: ClassificationSheet[]; logical_documents?: LogicalDocument[]; fragment_links?: FragmentLinks; coverage?: Classification['coverage']; input_messages?: unknown[]; input_summaries?: unknown[] } | null }
const props = withDefaults(defineProps<{ archiveOnSelect?: boolean }>(), { archiveOnSelect: false })
const emit = defineEmits<{ saved: []; stage: [stage: string] }>()
const file = ref<File | null>(null)
const files = ref<File[]>([])
const archiveKeys = ref<string[]>([])
const archiveProgress = ref('')
const archiveQuotaInfo = ref('')
const archiveQuotaMiB = ref<number | null>(null)
type ArchiveAsset = { id: string; name: string; state: string; versions: { id: string; version: number; status: string; sha256: string; classification_id: string | null }[] }
const archiveAssets = ref<ArchiveAsset[]>([])
const versionUploads = ref<Record<string, { file: File; requestKey: string }>>({})
const classifications = ref<Classification[]>([])
const selectedRows = ref<string[]>([])
const classificationConfirmed = computed(() => !!file.value && !!classifications.value[files.value.indexOf(file.value)]?.confirmed)
const classificationSampleAuthorized = ref(false)
const classificationOwnFileAuthorized = ref(false)
const cancelAnalysis = ref(false)
const analysisProgress = ref('')
const classificationNotice = ref('')
const analysisErrors = ref<Record<string, string>>({})
const autoSlices = ref<Record<string, { version: string; slices: AutoSlice[] }>>({})
const recentClassifications = ref<RecentClassification[]>([])
const selectedRegion = ref('')
const selectedRegionCoordinates = ref<{ sheet: string; range: string } | null>(null)
const selectedRegionNeedsChoice = ref(false)
const previewSelectionReady = computed(() => {
  const coordinates = selectedRegionCoordinates.value
  if (!coordinates) return !props.archiveOnSelect && !selectedRegionNeedsChoice.value
  const item = classifications.value[files.value.indexOf(file.value as File)]
  return item?.sheets.filter(sheet => sheet.sheet === coordinates.sheet)
    .flatMap(sheet => sheet.regions).filter(region => region.range === coordinates.range).length === 1
})
const selectedPrintArea = ref(false)
const batchLabel = ref('unknown')
const labelNames: Record<string, string> = { quotation: '报价', delivery: '送货', purchase: '采购', attendance: '考勤', production: '生产', process: '工艺', material: '原料', inspection: '检验', template: '模板', unknown: '未知/待理解' }
function classificationStatus(item: { confirmed?: boolean; model_status?: string; sheets: ClassificationSheet[] } | null) {
  if (!item) return '待确认'
  const unknown = item.sheets.some((sheet) => sheet.regions.some((region) => region.labels.includes('unknown')))
  if (item.confirmed && unknown) return '未知/待理解，用户已确认继续'
  if (item.confirmed) return item.model_status === 'returned' ? '模型建议已由用户确认' : '规则结果已由用户确认，模型未分析'
  return item.model_status === 'returned' ? '模型已返回，待确认' : '规则预筛，模型未分析'
}
const classificationGroups = computed(() => Object.entries(labelNames).map(([key, name]) => ({
  key, name, files: classifications.value.flatMap((item) => item.sheets.flatMap((sheet) => sheet.regions.filter((region) => region.labels.includes(key)).map((region) => `${item.name} / ${sheet.sheet} / ${region.range}`))),
})).filter((group) => group.files.length))
const name = ref('')
const review = ref<Review | null>(null)
const candidateIndex = ref(0)
const proposals = ref<Proposal[]>([])
const selectedVersion = ref(0)
const proposal = computed(() => proposals.value[selectedVersion.value])
const feedback = ref('')
const initialModel = ref(false)
const sampleAuthorized = ref(false)
const templateOwnFileAuthorized = ref(false)
const sheetIndex = ref(0)
const consent = ref(false)
const publishToTenant = ref(false)
const selected = computed(() => proposal.value?.candidates[candidateIndex.value]?.clear || [])
const error = ref('')
const busy = ref(false)
const savedId = ref('')
const savedModelStatus = ref('')
function layoutFor(index: number) { return index === 0 ? review.value?.layout?.[sheetIndex.value] : proposal.value?.result_previews?.[index - 1]?.layout?.[sheetIndex.value] }
function equivalentTo(index: number): number | null {
  const candidates = proposal.value?.candidates || []
  const signature = (candidate: Candidate) => JSON.stringify(candidate.clear.map((item) => JSON.stringify([item.sheet, item.cell])).sort())
  if (!candidates[index]) return null
  const prior = candidates.findIndex((candidate, i) => i < index && signature(candidate) === signature(candidates[index]))
  return prior < 0 ? null : prior + 1
}
function cellStyle(cell: LayoutCell): CSSProperties {
  return { fontWeight: cell.bold ? 'bold' : 'normal', fontStyle: cell.italic ? 'italic' : 'normal', fontSize: `${cell.font_size}pt`, color: /^[0-9a-fA-F]{6}$/.test(cell.font_color) ? `#${cell.font_color}` : undefined, backgroundColor: /^[0-9a-fA-F]{6}$/.test(cell.fill) ? `#${cell.fill}` : undefined, textAlign: ['left', 'right', 'center'].includes(cell.align) ? cell.align as CSSProperties['textAlign'] : undefined }
}
function switchVersion(index: number) { selectedVersion.value = index; candidateIndex.value = 0 }
let alive = true
let operationEpoch = 0
let selectionEpoch = 0
let selectedFilesCurrent: (() => boolean) | null = null
function captureOperation() {
  const currentSession = captureAuthSession(), epoch = operationEpoch
  return () => alive && epoch === operationEpoch && currentSession()
}
function captureFileOperation() {
  const current = captureOperation(), selectedScope = selectedFilesCurrent, epoch = selectionEpoch
  return () => current() && epoch === selectionEpoch && !!selectedScope?.()
}
function resetSelectionState() {
  autoSlices.value = {}
  file.value = null
  classifications.value = []
  classificationSampleAuthorized.value = false
  classificationOwnFileAuthorized.value = false
  selectedRows.value = []
  selectedRegion.value = ''
  selectedRegionCoordinates.value = null
  selectedRegionNeedsChoice.value = false
  selectedPrintArea.value = false
  name.value = ''
  review.value = null
  proposals.value = []
  selectedVersion.value = 0
  feedback.value = ''
  consent.value = false
  publishToTenant.value = false
  sampleAuthorized.value = false
  templateOwnFileAuthorized.value = false
  sheetIndex.value = 0
  candidateIndex.value = 0
  savedId.value = ''
  savedModelStatus.value = ''
  analysisProgress.value = ''; analysisErrors.value = {}; classificationNotice.value = ''
}
watch([getAuthSessionEpoch, () => productReadAccountEpoch.value], () => {
  const hadWork = busy.value || files.value.length || archiveAssets.value.length || recentClassifications.value.length
  operationEpoch += 1; selectionEpoch += 1; selectedFilesCurrent = null
  files.value = []; archiveKeys.value = []; archiveAssets.value = []; recentClassifications.value = []; versionUploads.value = {}
  archiveQuotaInfo.value = ''; archiveQuotaMiB.value = null; archiveProgress.value = ''
  resetSelectionState(); busy.value = false
  error.value = hadWork ? '登录身份已变化，已停止后续原件处理；请在当前账号重新选择文件，已发出的请求请在原账号核对。' : ''
  emit('stage', 'archive')
}, { flush: 'sync' })
onBeforeUnmount(() => { alive = false; operationEpoch += 1; selectionEpoch += 1 })
function choose(event: Event) {
  if (!alive || busy.value) return
  const input = event.target as HTMLInputElement
  files.value = Array.from(input.files || [])
  input.value = ''
  archiveKeys.value = files.value.map(() => crypto.randomUUID())
  archiveProgress.value = ''
  selectionEpoch += 1; selectedFilesCurrent = captureAuthSession()
  resetSelectionState()
  error.value = files.value.length > 200 ? '一次最多上传 200 个文件，请分批上传' : ''
  analysisProgress.value = ''; analysisErrors.value = {}
  classificationNotice.value = ''
  emit('stage', 'archive')
  if (props.archiveOnSelect) void classify()
}
async function classify() {
  const current = captureFileOperation()
  if (!current()) return
  if (busy.value || !files.value.length || files.value.length > 200) return
  if (files.value.reduce((sum, item) => sum + item.size, 0) > 50 * 1024 * 1024) {
    error.value = '本批文件超过 50 MB，请分批上传'; return
  }
  busy.value = true; error.value = ''
  emit('stage', 'classification')
  try {
    const previousSelection = file.value
    const results: Classification[] = []
    const batchFiles = [...files.value], requestKeys = [...archiveKeys.value]
    for (const [index, item] of batchFiles.entries()) {
      if (!current()) return
      const existing = props.archiveOnSelect ? classifications.value[index] : undefined
      if (existing?.status === 'classified') { results.push(existing); continue }
      archiveProgress.value = `归档及分类 ${index + 1}/${files.value.length}：${item.name}`
      try {
        const form = new FormData(); form.append('file', item); form.append('request_key', requestKeys[index])
        const result = await templatePreviewApi.archiveClassifyExcel(form) as Classification
        if (!current()) return
        results.push(result)
      } catch (err) { if (!current()) return;
        results.push({ name: item.name, status: 'unsupported', sheets: [], message: `${err instanceof Error ? err.message : '归档或分类未完成'}；请先查看原件档案核对，勿重新选择文件重复上传。` })
      }
    }
    if (!current()) return
    classifications.value = results
    archiveProgress.value = props.archiveOnSelect && results.every((item) => item.status === 'classified')
      ? '原件已归档并完成规则预筛，请继续核对单据分类、片段边界和续表关系。'
      : '本批处理结束；失败或结果未知的文件不可继续，请核对后重试。'
    const index = results.findIndex((item) => item.status === 'classified')
    if (index >= 0 && (!props.archiveOnSelect || !previousSelection || results[files.value.indexOf(previousSelection)]?.status !== 'classified')) selectFile(index)
    if (index >= 0) emit('stage', classificationConfirmed.value ? review.value ? 'template' : 'cleaning' : 'fragments')
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '分类失败' }
  finally { if (current()) busy.value = false }
}
async function loadArchiveQuota() {
  const current = captureOperation()
  if (!current()) return
  try {
    const quota = await templatePreviewApi.archiveQuota() as { configured: boolean; limit_bytes: number | null; reserved_bytes: number }
    if (!current()) return
    archiveQuotaInfo.value = quota.configured ? `已预留 ${quota.reserved_bytes} / ${quota.limit_bytes} 字节` : '尚未设置配额，不能归档'
  } catch (err) { if (!current()) return; archiveQuotaInfo.value = err instanceof Error ? err.message : '无法读取配额' }
}
async function saveArchiveQuota() {
  const current = captureOperation()
  if (!current()) return
  const value = archiveQuotaMiB.value
  if (!value || !Number.isSafeInteger(value) || value < 1 || value > 1048576) { archiveQuotaInfo.value = '请输入 1 至 1048576 MiB 的整数'; return }
  try {
    const form = new FormData(); form.append('limit_bytes', String(value * 1024 * 1024))
    await templatePreviewApi.setArchiveQuota(form)
    if (!current()) return
    await loadArchiveQuota()
  } catch (err) { if (!current()) return; archiveQuotaInfo.value = err instanceof Error ? err.message : '配额设置失败' }
}
async function loadArchiveAssets() {
  const current = captureOperation()
  if (!current()) return
  try {
    const result = await templatePreviewApi.archiveAssets() as { assets: ArchiveAsset[] }
    if (!current()) return
    archiveAssets.value = result.assets
  }
  catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '归档列表读取失败' }
}
async function changeArchiveState(asset: ArchiveAsset, state: string) {
  const current = captureOperation()
  if (!current()) return
  if (state === 'trashed' && !window.confirm(`撤回 ${asset.name}？原件保留，可恢复；存在分类依赖时不能撤回。`)) return
  try {
    const form = new FormData(); form.append('state', state)
    await templatePreviewApi.setArchiveAssetState(asset.id, form)
    if (!current()) return
    await loadArchiveAssets()
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '归档状态更新失败' }
}
async function recoverArchive(versionId: string) {
  const current = captureOperation()
  if (!current()) return
  try {
    await templatePreviewApi.recoverArchiveVersion(versionId, new FormData())
    if (!current()) return
    await loadArchiveAssets()
  }
  catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '核对失败，未修改原件' }
}
function chooseArchiveVersion(assetId: string, event: Event) {
  if (!alive || busy.value) return
  const chosen = (event.target as HTMLInputElement).files?.[0]
  if (chosen) versionUploads.value[assetId] = { file: chosen, requestKey: crypto.randomUUID() }
}
async function appendArchiveVersion(asset: ArchiveAsset) {
  const current = captureOperation()
  if (!current()) return
  const selected = versionUploads.value[asset.id]
  if (!selected) return
  busy.value = true; error.value = ''
  try {
    const form = new FormData(); form.append('file', selected.file); form.append('request_key', selected.requestKey)
    await templatePreviewApi.appendArchiveVersion(asset.id, form)
    if (!current()) return
    delete versionUploads.value[asset.id]
    await loadArchiveAssets()
  } catch (err) { if (!current()) return; error.value = (err instanceof Error ? err.message : '版本写入失败') + '；结果未知时请先查看档案，勿重新选择文件重复提交。' }
  finally { if (current()) busy.value = false }
}
async function downloadArchiveVersion(versionId: string, name: string) {
  const current = captureOperation()
  if (!current()) return
  try {
    const response = await templatePreviewApi.downloadArchiveVersion(versionId)
    if (!current()) return
    const blob = await response.blob()
    if (!current()) return
    const url = URL.createObjectURL(blob); const link = document.createElement('a')
    link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url)
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '原件读取失败' }
}
async function classifyArchiveVersion(versionId: string, name: string) {
  const current = captureOperation()
  if (!current()) return
  busy.value = true; error.value = ''
  try {
    const item = await templatePreviewApi.classifyArchiveVersion(versionId, new FormData()) as Classification
    if (!current()) return
    const response = await templatePreviewApi.downloadArchiveVersion(versionId)
    if (!current()) return
    const blob = await response.blob()
    if (!current()) return
    selectedFilesCurrent = captureAuthSession(); selectionEpoch += 1
    files.value = [new File([blob], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })]
    classifications.value = [item]; selectFile(0); await loadArchiveAssets()
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '分类失败，请查看档案后核对' }
  finally { if (current()) busy.value = false }
}
function selectFile(index: number) {
  if (classifications.value[index]?.status !== 'classified') return
  file.value = files.value[index]
  classificationOwnFileAuthorized.value = false
  selectedPrintArea.value = false
  sampleAuthorized.value = false; templateOwnFileAuthorized.value = false; consent.value = false; publishToTenant.value = false
  name.value = file.value.name.replace(/\.xlsx$/i, '')
  const firstSheet = classifications.value[index]?.sheets[0]
  selectedRegion.value = firstSheet?.regions[0] ? `${firstSheet.sheet} / ${firstSheet.regions[0].range}` : ''
  selectedRegionCoordinates.value = firstSheet?.regions[0] ? { sheet: firstSheet.sheet, range: firstSheet.regions[0].range } : null
  selectedRegionNeedsChoice.value = false
  review.value = null; proposals.value = []; selectedVersion.value = 0; candidateIndex.value = 0; savedId.value = ''
  emit('stage', classifications.value[index].confirmed ? 'cleaning' : 'fragments')
}
function selectRegion(i: number, j: number, k: number) {
  const neededChoice = selectedRegionNeedsChoice.value
  if (file.value !== files.value[i]) selectFile(i)
  const sheet = classifications.value[i].sheets[j]
  selectedRegion.value = `${sheet.sheet} / ${sheet.regions[k].range}`
  selectedRegionCoordinates.value = { sheet: sheet.sheet, range: sheet.regions[k].range }
  selectedRegionNeedsChoice.value = false
  if (neededChoice) classificationNotice.value = classifications.value[i].confirmed ? '' : '已选择新的文档片段，请再次确认分类和续表关系后清理。'
  selectedPrintArea.value = false
  review.value = null; proposals.value = []; selectedVersion.value = 0; candidateIndex.value = 0; savedId.value = ''
  sampleAuthorized.value = false; templateOwnFileAuthorized.value = false; consent.value = false; publishToTenant.value = false
  if (props.archiveOnSelect) name.value = `${file.value?.name.replace(/\.xlsx$/i, '')} · ${sheet.sheet} ${sheet.regions[k].range}`
  emit('stage', classifications.value[i].confirmed ? 'cleaning' : 'fragments')
}
function splitRegion(item: Classification, sheet: ClassificationSheet, region: ClassificationRegion) {
  const ranges = (region.splitDraft || '').split(/\r?\n/).map((value) => value.trim().toUpperCase()).filter(Boolean)
  if (ranges.length < 2 || ranges.length > 200 || ranges.some((value) => !/^[A-Z]{1,3}[1-9]\d*:[A-Z]{1,3}[1-9]\d*$/.test(value))) {
    error.value = '请逐行填写 2 至 200 个完整区域，如 A1:F12；拆分须完整覆盖原片段，不能重叠或切断合并单元格。'
    return
  }
  sheet.regions.splice(sheet.regions.indexOf(region), 1, ...ranges.map((range) => ({ ...region, range,
    original_range: region.original_range || region.range, labels: [...region.labels], modified: true, splitDraft: undefined })))
  item.confirmed = false; item.fragment_links = undefined; item.logical_documents = []; item.confirmed_document_count = null
  selectedRows.value = []; review.value = null; proposals.value = []; publishToTenant.value = false
  classificationNotice.value = '片段边界已编辑，须提交分类核对；服务端校验通过后，还需重新核对新片段与续表关系并再次确认。'
  error.value = ''
  const i = classifications.value.indexOf(item), j = item.sheets.indexOf(sheet)
  selectRegion(i, j, sheet.regions.findIndex((entry) => entry.original_range === (region.original_range || region.range)))
}
function toggleLabel(sheet: ClassificationRegion, label: string, checked: boolean) {
  sheet.modified = true
  for (const item of classifications.value) if (item.sheets.some((entry) => entry.regions.includes(sheet))) invalidateClassification(item)
  const next = new Set(sheet.labels)
  if (checked) next.add(label)
  else next.delete(label)
  if (label === 'unknown' && checked) { sheet.labels = ['unknown']; return }
  if (checked) next.delete('unknown')
  sheet.labels = [...next]; if (!sheet.labels.length) sheet.labels = ['unknown']
}
function changeRegionRange(region: ClassificationRegion, sheet: ClassificationSheet, value: string) {
  value = normalizeRegionRange(value)
  const oldRange = region.range
  if (!region.original_range) region.original_range = oldRange
  region.range = value; region.modified = true
  for (const item of classifications.value) if (item.sheets.includes(sheet)) invalidateClassification(item)
  if (selectedRegionCoordinates.value?.sheet === sheet.sheet && selectedRegionCoordinates.value.range === oldRange) {
    selectedRegionCoordinates.value = { sheet: sheet.sheet, range: value }
    selectedRegion.value = `${sheet.sheet} / ${value}`
  }
}
function normalizeRegionRange(value: string) {
  const match = value.trim().match(/^\$?([a-z]{1,3})\$?([1-9]\d*)\s*:\s*\$?([a-z]{1,3})\$?([1-9]\d*)$/i)
  return match ? `${match[1].toUpperCase()}${match[2]}:${match[3].toUpperCase()}${match[4]}` : value
}
function alignConfirmedSelection(item: Classification) {
  const index = classifications.value.indexOf(item)
  if (index < 0 || !file.value || index !== files.value.indexOf(file.value)) return
  const previous = selectedRegionCoordinates.value
  const matches = previous ? item.sheets.filter(sheet => sheet.sheet === previous.sheet).flatMap(sheet =>
    sheet.regions.filter(region => normalizeRegionRange(region.range) === normalizeRegionRange(previous.range))
      .map(region => ({ sheet: sheet.sheet, range: region.range }))) : []
  review.value = null; proposals.value = []; selectedVersion.value = 0; candidateIndex.value = 0; savedId.value = ''
  selectedPrintArea.value = false; sampleAuthorized.value = false; templateOwnFileAuthorized.value = false
  classificationSampleAuthorized.value = false; classificationOwnFileAuthorized.value = false
  consent.value = false; publishToTenant.value = false
  if (matches.length === 1) {
    selectedRegionCoordinates.value = matches[0]
    selectedRegion.value = `${matches[0].sheet} / ${matches[0].range}`
    selectedRegionNeedsChoice.value = false
  } else if (previous || props.archiveOnSelect || selectedRegionNeedsChoice.value) {
    selectedRegionCoordinates.value = null; selectedRegion.value = ''; selectedRegionNeedsChoice.value = true
    classificationNotice.value = `${item.confirmed ? '' : `${classificationNotice.value} `}当前所选片段已变化，请从确认后的文档片段中重新选择，再预览清理候选。`
  }
}
function applyBatchLabel() {
  classifications.value.forEach((item, i) => item.sheets.forEach((sheet, j) => sheet.regions.forEach((region, k) => {
    if (selectedRows.value.includes(`${i}:${j}:${k}`)) { region.labels = [batchLabel.value]; region.modified = true; invalidateClassification(item) }
  })))
}
function invalidateClassification(item: Classification) {
  item.confirmed = false
  if (item === classifications.value[files.value.indexOf(file.value as File)]) {
    review.value = null; proposals.value = []; publishToTenant.value = false; consent.value = false
    sampleAuthorized.value = false; templateOwnFileAuthorized.value = false
    emit('stage', 'fragments')
  }
}
async function analyzeClassifications() {
  const current = captureFileOperation()
  if (!current()) return
  if (classificationSampleAuthorized.value === classificationOwnFileAuthorized.value) return
  busy.value = true; error.value = ''; cancelAnalysis.value = false
  const selectedFile = classifications.value[files.value.indexOf(file.value as File)]
  const pending = classifications.value.filter((item) => (!classificationOwnFileAuthorized.value || item === selectedFile) && item.status === 'classified' && item.model_status !== 'returned' && !item.confirmed && item.checkpoint?.phase !== 'inflight')
  try {
    for (const [index, item] of pending.entries()) {
      if (cancelAnalysis.value) break
      analysisProgress.value = `模型分析 ${index + 1}/${pending.length}：${item.name}`
      try {
        if (!item.classification_id || !item.version) throw new Error('分类来源或版本缺失，请重新分类')
        while (!cancelAnalysis.value) {
          const form = new FormData(); form.append('version', item.version); form.append(classificationOwnFileAuthorized.value ? 'own_file_authorized' : 'sample_authorized', 'true')
          form.append('auto_group', 'true')
          if (item.checkpoint?.phase === 'paused') form.append('continue_authorized', 'true')
          const result = await templatePreviewApi.analyzeClassification(item.classification_id, form) as { phase?: string; checkpoint?: Checkpoint; version: string; sheets: ClassificationSheet[]; model_status: string; budget?: Classification['budget']; suggested_documents?: SuggestedDocument[]; suggested_document_count?: number | null; fragment_links?: FragmentLinks; coverage: Classification['coverage']; input_messages?: unknown[]; input_summaries?: unknown[] }
          if (!current()) return
          if (result.phase === 'pending' || result.phase === 'paused') {
            item.checkpoint = result.checkpoint
            analysisProgress.value = `${item.name}：已完成 ${result.checkpoint?.completed}/${result.checkpoint?.total} 批`
            if (result.phase === 'paused') break
            continue
          }
          item.checkpoint = null; item.version = result.version; item.sheets = result.sheets; item.model_status = result.model_status; item.budget = result.budget; item.suggested_documents = result.suggested_documents; item.suggested_document_count = result.suggested_document_count; item.fragment_links = result.fragment_links; item.coverage = result.coverage; item.input_messages = result.input_messages; item.input_summaries = result.input_summaries; item.confirmed = false
          try {
            const generated = await templatePreviewApi.autoSlices(item.classification_id, result.version) as { slices: AutoSlice[] }
            if (!current()) return
            autoSlices.value[item.classification_id] = { version: result.version, slices: generated.slices }
          } catch (err) {
            if (!current()) return
            analysisErrors.value[item.classification_id] = err instanceof Error ? `裁切失败：${err.message}` : '裁切失败，请检查模型边界及依赖'
          }
          break
        }
      } catch (err) { if (!current()) return;
        const message = err instanceof Error ? err.message : '分析失败'
        if (message.includes('未调用模型')) {
          analysisErrors.value[item.classification_id || item.name] = message
        } else {
          analysisErrors.value[item.classification_id || item.name] = message + '；请求结果可能未知，请查看已保存分类核对，勿重复发送'
          item.checkpoint = { phase: 'inflight', version: item.version || '', completed: item.checkpoint?.completed || 0, total: item.checkpoint?.total || 0, max_calls: item.checkpoint?.max_calls || 1, message: '结果未知，不可重发；需人工核对，当前无解锁入口' }
        }
      }
    }
    analysisProgress.value = cancelAnalysis.value ? '已停止后续批次；当前请求可能已完成，请查看已保存分类。' : classifications.value.some((item) => item.checkpoint?.phase === 'inflight') ? '部分请求结果未知，不可重发，需人工核对。' : classifications.value.some((item) => item.checkpoint?.phase === 'paused') ? '本轮预算已用完；可再次点击模型分析继续剩余批次。' : '本轮分析结束。'
    selectedRows.value = []
    const index = files.value.indexOf(file.value as File)
    if (index >= 0) selectFile(index)
  } finally { if (current()) busy.value = false }
}
async function previewAutoSlice(index: number, slice: AutoSlice) {
  if (file.value !== files.value[index]) selectFile(index)
  name.value = slice.filename.replace(/\.xlsx$/i, '')
  await preview(slice)
}
async function downloadAutoSlice(item: Classification, slice: AutoSlice) {
  const current = captureFileOperation()
  if (!current()) return
  if (!item.classification_id || !item.version || autoSlices.value[item.classification_id]?.version !== item.version) return
  try {
    const response = await templatePreviewApi.downloadAutoSlice(item.classification_id, item.version, slice.index)
    if (!current()) return
    const blob = await response.blob()
    if (!current()) return
    const url = URL.createObjectURL(blob); const link = document.createElement('a')
    link.href = url; link.download = slice.filename; link.click(); URL.revokeObjectURL(url)
  } catch (err) { if (current()) error.value = err instanceof Error ? err.message : '下载失败' }
}
async function confirmClassifications() {
  const current = captureFileOperation()
  if (!current()) return
  busy.value = true; error.value = ''
  try {
    for (const item of classifications.value) {
      if (item.status !== 'classified') continue
      if (!item.classification_id || !item.version) throw new Error('分类来源或版本缺失，请重新分类')
      if (item.confirmed) continue
      const labels = item.sheets.flatMap((sheet) => sheet.regions.map((region) => ({ sheet: sheet.sheet, original_range: region.original_range || region.range, range: region.range, labels: region.labels })))
      const links = item.sheets.some((sheet) => sheet.regions.some((region) => region.modified)) ? [] : (item.fragment_links?.items || []).filter((link) => link.selected).map(({ sheet, first, second }) => ({ sheet, first, second }))
      const form = new FormData(); form.append('version', item.version); form.append('labels_json', JSON.stringify(labels)); form.append('links_json', JSON.stringify(links)); form.append('independent_confirmed', String(!!item.independent_confirmed))
      const result = await templatePreviewApi.confirmClassification(item.classification_id, form) as { message?: string; version: string; confirmed: boolean; sheets: ClassificationSheet[]; fragment_links?: FragmentLinks; logical_documents?: LogicalDocument[]; confirmed_document_count?: number | null; document_count_status?: string; coverage?: Classification['coverage'] }
      if (!current()) return
      item.version = result.version; item.confirmed = result.confirmed; item.sheets = result.sheets; item.fragment_links = result.fragment_links; item.logical_documents = result.logical_documents; item.confirmed_document_count = result.confirmed_document_count; item.document_count_status = result.document_count_status; item.coverage = result.coverage
      if (!result.confirmed) classificationNotice.value = result.message || '拆分已保存。请核对新的文档片段和续表关系，再次确认后才能清理模板。'
      alignConfirmedSelection(item)
    }
    if (classificationConfirmed.value && previewSelectionReady.value) { classificationNotice.value = ''; emit('stage', 'cleaning') }
    else emit('stage', 'fragments')
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '分类确认失败，请刷新后重试' }
  finally { if (current()) busy.value = false }
}
async function loadRecentClassifications() {
  const current = captureOperation()
  if (!current()) return
  busy.value = true; error.value = ''
  try {
    const result = await templatePreviewApi.recentClassifications() as { files: typeof recentClassifications.value }
    if (!current()) return
    recentClassifications.value = result.files
  }
  catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '分类记录读取失败' }
  finally { if (current()) busy.value = false }
}
async function restoreClassification(item: RecentClassification) {
  const current = captureOperation()
  if (!current()) return
  if ((!item.archive_version_id && files.value.length !== 1) || !item.latest) return
  busy.value = true; error.value = ''
  try {
    if (item.archive_version_id) {
      const response = await templatePreviewApi.downloadClassificationSource(item.classification_id)
      if (!current()) return
      const blob = await response.blob()
      if (!current()) return
      selectedFilesCurrent = captureAuthSession(); selectionEpoch += 1
      files.value = [new File([blob], item.name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })]
    }
    if (!globalThis.crypto?.subtle) throw new Error('当前环境不能校验文件哈希，请使用安全连接')
    const source = await files.value[0].arrayBuffer()
    if (!current()) return
    const digest = await globalThis.crypto.subtle.digest('SHA-256', source)
    if (!current()) return
    const sha = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
    if (sha !== item.sha256) throw new Error('所选文件与分类来源不一致')
    classifications.value = [{ name: files.value[0].name, status: 'classified', sha256: sha,
      classification_id: item.classification_id, ...item.latest, checkpoint: item.checkpoint, template_write_state: item.template_write_state }]
    selectFile(0)
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '恢复分类失败' }
  finally { if (current()) busy.value = false }
}
async function preview(slice?: AutoSlice) {
  const current = captureFileOperation()
  if (!current()) return
  if (!file.value || (!slice && (!classificationConfirmed.value || !previewSelectionReady.value))) return
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('file', file.value)
    form.append('model_opt_in', String(initialModel.value))
    form.append('sample_authorized', String(sampleAuthorized.value))
    form.append('own_file_authorized', String(templateOwnFileAuthorized.value))
    const selectedFile = classifications.value[files.value.indexOf(file.value)]
    if (slice) {
      const available = selectedFile?.classification_id && selectedFile.version && autoSlices.value[selectedFile.classification_id]
      if (!available || available.version !== selectedFile.version || !available.slices.some(item => item.index === slice.index && item.sha256 === slice.sha256)) throw new Error('裁切结果已变化，请重新选择')
      form.append('classification_id', selectedFile.classification_id!); form.append('classification_version', selectedFile.version!)
      form.append('auto_slice_index', String(slice.index))
    } else if (selectedFile?.classification_id && selectedFile.version && selectedRegionCoordinates.value) {
      form.append('classification_id', selectedFile.classification_id); form.append('classification_version', selectedFile.version)
      form.append('region_sheet', selectedRegionCoordinates.value.sheet); form.append('region_range', selectedRegionCoordinates.value.range)
      form.append('print_area_mode', selectedPrintArea.value ? 'selected' : 'source')
    }
    const result = await templatePreviewApi.reviewExcel(form) as Review
    if (!current()) return
    proposals.value = result.versions?.length ? result.versions : [result.proposal]
    selectedVersion.value = proposals.value.length - 1
    candidateIndex.value = 0
    review.value = result
    emit('stage', 'template')
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '预览失败' }
  finally { if (current()) busy.value = false }
}
async function save() {
  const current = captureFileOperation()
  if (!current()) return
  if (!file.value || !review.value || !name.value.trim()) return
  if (review.value.selected_region?.selection_basis !== 'model_group' && (!classificationConfirmed.value || !previewSelectionReady.value)) return
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('name', name.value.trim())
    form.append('publish_to_tenant', String(publishToTenant.value))
    form.append('review_id', review.value.review_id)
    form.append('proposal_version', proposal.value.version)
    form.append('candidate_id', proposal.value.candidates[candidateIndex.value].id)
    form.append('selections', JSON.stringify(selected.value))
    const result = await templatePreviewApi.saveReviewedExcel(form) as { template_id: string }
    if (!current()) return
    savedId.value = result.template_id
    savedModelStatus.value = proposal.value.candidates[candidateIndex.value].id.startsWith('model_') ? '已选择模型建议，并以本次确认的清理范围保存。' : '本次保存使用规则或人工选择。'
    review.value = null
    emit('saved')
  } catch (err) { if (!current()) return; error.value = `${err instanceof Error ? err.message : '保存失败'}；如果结果未知，请先核对模板库和分类记录，勿重复提交。` }
  finally { if (current()) busy.value = false }
}
async function refine() {
  const current = captureFileOperation()
  if (!current()) return
  if (!file.value || !review.value || !proposal.value || !consent.value || !feedback.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    const form = new FormData()
    form.append('review_id', review.value.review_id)
    form.append('parent_version', proposal.value.version)
    form.append('feedback', feedback.value.trim())
    form.append('current', JSON.stringify(selected.value))
    form.append('consent', 'true')
    form.append('sample_authorized', String(sampleAuthorized.value))
    form.append('own_file_authorized', String(templateOwnFileAuthorized.value))
    const result = await templatePreviewApi.refineReviewedExcel(form) as { proposal: Proposal }
    if (!current()) return
    proposals.value.push(result.proposal)
    selectedVersion.value = proposals.value.length - 1
    candidateIndex.value = 0
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '模型不可用，原候选未改变' }
  finally { if (current()) busy.value = false }
}
async function download(id: string) {
  const current = captureOperation()
  if (!current()) return
  busy.value = true
  error.value = ''
  try {
    const response = await templatePreviewApi.downloadReviewedExcel(id)
    if (!current()) return
    const blob = await response.blob()
    if (!current()) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${name.value || '模板'}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '下载失败' }
  finally { if (current()) busy.value = false }
}
async function downloadCandidate(index: number) {
  const current = captureFileOperation()
  if (!current()) return
  if (!review.value) return
  busy.value = true
  error.value = ''
  try {
    const response = await templatePreviewApi.downloadReviewedCandidate(review.value.review_id, proposal.value.version, proposal.value.candidates[index].id)
    if (!current()) return
    const blob = await response.blob()
    if (!current()) return
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `候选模板-${index + 1}.xlsx`; link.click(); URL.revokeObjectURL(url)
  } catch (err) { if (!current()) return; error.value = err instanceof Error ? err.message : '候选下载失败' }
  finally { if (current()) busy.value = false }
}
</script>

<template>
  <section class="reviewed-template" aria-label="Excel 模板清理">
    <div class="reviewed-template__step">
    <h3>第一步：原件归档</h3>
    <p>原件长期保留，不会自动删除；撤回后可恢复，存在分类依赖时不能撤回。永久清除尚未开放。未配置归档配额或配额不足时不能归档。</p>
    <details><summary>管理员：归档配额</summary>
      <button type="button" :disabled="busy" @click="loadArchiveQuota">查看配额</button>
      <p>{{ archiveQuotaInfo }}</p>
      <label>配额（MiB）：<input v-model.number="archiveQuotaMiB" type="number" min="1" max="1048576" step="1"></label>
      <button type="button" :disabled="busy" @click="saveArchiveQuota">设置配额</button>
    </details>
    <button type="button" :disabled="busy" @click="loadArchiveAssets">查看原件档案</button>
    <div v-for="asset in archiveAssets" :key="asset.id">
      <p>{{ asset.name }} · {{ asset.state === 'active' ? '已归档' : '已撤回' }} · {{ asset.id }}</p>
      <p v-for="entry in asset.versions" :key="entry.id">版本 {{ entry.version }} · {{ entry.status }} · {{ entry.sha256 }}
        <button v-if="entry.status === 'pending'" type="button" :disabled="busy" @click="recoverArchive(entry.id)">核对完整性并恢复</button>
        <button v-if="entry.status === 'ready' && asset.state === 'active'" type="button" :disabled="busy" @click="downloadArchiveVersion(entry.id, asset.name)">下载原件版本</button>
        <button v-if="entry.status === 'ready' && asset.state === 'active'" type="button" :disabled="busy" @click="classifyArchiveVersion(entry.id, asset.name)">分类此版本</button>
      </p>
      <label v-if="asset.state === 'active'">为此档案新增版本：<input type="file" accept=".xlsx" :disabled="busy" @change="chooseArchiveVersion(asset.id, $event)"></label>
      <button v-if="asset.state === 'active'" type="button" :disabled="busy || !versionUploads[asset.id]" @click="appendArchiveVersion(asset)">保存新版本</button>
      <button v-if="asset.state === 'active'" type="button" :disabled="busy" @click="changeArchiveState(asset, 'trashed')">撤回</button>
      <button v-else type="button" :disabled="busy" @click="changeArchiveState(asset, 'active')">恢复</button>
    </div>
    <p>分类先做规则预筛；可选择模型分析。分类仅供确认，不关联业务库或写入业务数据。依据及未读范围需核对，不表示理解全部语义。</p>
    <input type="file" accept=".xlsx" multiple :disabled="busy" @change="choose">
    <p class="reviewed-template__limits">模板归档流水线：每批最多 200 个文件，单个不超过 20 MB，整批不超过 50 MB<span v-if="!archiveOnSelect">（与旧业务导入单文件 100 MB 上限不同）</span>；超出请分批。</p>
    <button v-if="!archiveOnSelect || classifications.some((item) => item.status !== 'classified')" type="button" :disabled="!files.length || files.length > 200 || busy" @click="classify">{{ archiveOnSelect ? '重试未完成文件' : '归档并分类所选文件' }}</button>
    <p v-if="archiveProgress" role="status">{{ archiveProgress }}</p>
    </div>
    <div class="reviewed-template__step">
    <h3>第二步：文件分类</h3>
    <p v-if="classificationNotice" role="status">{{ classificationNotice }}</p>
    <button type="button" :disabled="busy" @click="loadRecentClassifications">查看已保存分类</button>
    <details v-if="recentClassifications.length"><summary>已保存分类（归档来源可直接恢复；旧记录需选择相同原文件）</summary>
      <div v-for="item in recentClassifications" :key="item.sha256"><p>{{ item.name }} · {{ item.sha256 }} · {{ classificationStatus(item.latest) }}</p>
        <p v-if="item.template_write_state === 'locked'">模板保存正在进行或结果待核对；请勿重复保存，当前没有自动解锁入口。</p>
        <p v-for="sheet in item.latest?.sheets || []" :key="sheet.sheet">{{ sheet.sheet }}：{{ sheet.regions.map((region) => `${region.range} ${region.labels.map((label) => labelNames[label] || label).join('、')}`).join('；') }}</p>
        <button type="button" :disabled="busy || (!item.archive_version_id && files.length !== 1)" @click="restoreClassification(item)">恢复此分类并继续</button>
      </div>
    </details>
    <div v-if="classifications.length" class="classification-results">
      <label><input v-model="classificationSampleAuthorized" type="checkbox" :disabled="busy"> 确认所有待分析文件为获准发送的合成或公开样本，同意发送有界单元格及结构（每文件每轮默认一次，按服务配置最多四次，逐次执行；预算用完需再次确认）</label>
      <label v-if="file"><input v-model="classificationOwnFileAuthorized" type="checkbox" :disabled="busy"> 我有权授权当前文件 {{ file.name }} 的内容发送至 MiMo：每批最多 500 个单元格的文本、公式和结构坐标可能包含敏感数据；仅发送当前文件，逐批分析，每轮最多四次。</label>
      <button type="button" :disabled="busy || classificationSampleAuthorized === classificationOwnFileAuthorized" @click="analyzeClassifications()">模型分析已分类文件</button>
      <button v-if="busy && analysisProgress" type="button" @click="cancelAnalysis = true">停止后续分析</button>
      <p v-if="analysisProgress">{{ analysisProgress }}</p>
      <p>下方坐标是物理片段；是否属于同一业务文档需另行核对。同类别不会自动合并，范围可能包含空白边缘，不表示已精确裁剪。</p>
      <p v-for="group in classificationGroups" :key="group.key">{{ group.name }}：{{ group.files.join('；') }}</p>
      <label>批量设为 <select v-model="batchLabel"><option v-for="(label, key) in labelNames" :key="key" :value="key">{{ label }}</option></select></label>
      <button type="button" :disabled="!selectedRows.length || busy" @click="applyBatchLabel">应用到选中区域</button>
      <div v-for="(item, i) in classifications" :key="i">
        <label><input type="radio" name="template-file" :checked="file === files[i]" :disabled="busy || item.status !== 'classified'" @change="selectFile(i)"> {{ item.name }}</label>
        <small v-if="item.sha256">来源 SHA-256：{{ item.sha256 }}</small>
        <p v-if="item.read_only_print_areas?.length">原打印区域：{{ item.read_only_print_areas.map((area) => `${area.sheet}: ${area.value}`).join('；') }}。逐文档提取时可能需要确认派生打印区域。</p>
        <small v-if="item.checkpoint">批次 {{ item.checkpoint.completed }}/{{ item.checkpoint.total }}；本轮 {{ item.checkpoint.calls_in_round ?? 0 }}/{{ item.checkpoint.max_calls }} 次：{{ item.checkpoint.message }}；停止只在批次之间生效。</small>
        <small v-if="item.template_write_state === 'locked'">模板保存正在进行或结果待核对；请勿重复保存，当前没有自动解锁入口。</small>
        <small v-if="item.status === 'classified'">{{ classificationStatus(item) }}</small>
        <template v-if="!item.sheets.some((sheet) => sheet.regions.some((region) => region.modified))">
          <p v-if="item.model_status === 'returned' && item.confirmed_document_count == null">逻辑文档总数待确认：跨批关系、未读或未分配内容可能尚未解决。</p>
          <p v-if="item.confirmed_document_count != null">已确认 {{ item.confirmed_document_count }} 个逻辑文档。</p>
          <p v-for="group in item.suggested_documents || []" :key="group.document_id">模型分组建议 {{ group.document_id }}：{{ group.fragments.map((part) => `${part.sheet}!${part.range}`).join('、') }}；仅供核对，未确认。</p>
        </template>
        <div v-if="item.fragment_links?.items.length && !item.sheets.some((sheet) => sheet.regions.some((region) => region.modified))">
          <p>可能的片段关联（仅供核对，尚未确认或合并）：</p>
          <p v-for="link in item.fragment_links.items" :key="`${link.sheet}:${link.first}:${link.second}`"><label><input v-model="link.selected" type="checkbox" :disabled="busy || link.status !== 'candidate'" @change="invalidateClassification(item)"> 同一文档</label> {{ link.sheet }}：{{ link.first }} ↔ {{ link.second }}；{{ link.model_group_suggested ? '模型建议同组；' : '' }}{{ link.repeated_header_observed ? '观察到重复表头；' : '' }}{{ link.shared_dependencies.length ? `模型共同引用 ${link.shared_dependencies.map((ref) => `${ref.sheet}!${ref.cell}`).join('、')}；` : '' }}{{ link.status === 'identity_conflict' ? '单据身份信息不一致，不能按续表合并，请核对。' : '关联仍待确认。' }}</p>
          <p v-if="item.fragment_links.omitted">还有 {{ item.fragment_links.omitted }} 条候选未展示。</p>
        </div>
        <p v-else-if="item.fragment_links?.items.length">区域已修改，之前的关联候选不再适用，请重新核对。</p>
        <label v-if="item.model_status === 'returned'"><input v-model="item.independent_confirmed" type="checkbox" :disabled="busy" @change="invalidateClassification(item)"> 我已核对未勾选关联的有内容片段各自是独立文档；仅完整覆盖且无未知内容时计算总数。</label>
        <p v-for="group in item.logical_documents || []" :key="group.logical_document_id">已确认同一文档：{{ group.fragments.map((part) => `${part.sheet}!${part.range}`).join('、') }}；取消勾选后重新确认可拆分。</p>
        <details v-if="item.input_summaries?.length"><summary>查看模型输入摘要及来源坐标（不含正文）</summary><pre>{{ JSON.stringify(item.input_summaries, null, 2) }}</pre></details>
        <details v-if="item.input_messages?.length"><summary>历史记录中的模型输入正文（旧记录未自动清理）</summary><pre>{{ JSON.stringify(item.input_messages, null, 2) }}</pre></details>
        <p v-if="item.model_status === 'returned'">模型仅分析下列已发送范围；未读或未分配部分仍待确认，不能视为全文件分类完成。<span v-if="item.budget"> 已调用 {{ item.budget.calls }} 次（每轮上限 {{ item.budget.max_calls }} 次）；尚有 {{ item.budget.unread }} 格未发送。</span></p>
        <p v-for="coverage in item.coverage || []" :key="coverage.sheet">{{ coverage.sheet }}：发送 {{ coverage.sent }}/{{ coverage.total }} 格；未发送 {{ coverage.unread.length }} 格，未归入区域 {{ coverage.unassigned.length }} 格，合并范围未发送 {{ coverage.merged_omitted }} 个，仍待确认。<span v-if="coverage.deferred_oversized_rows?.length"> {{ coverage.deferred_oversized_rows.length }} 格所在行超出安全预算，需人工处理。</span></p>
        <details v-for="coverage in item.coverage || []" :key="`coverage-${coverage.sheet}`"><summary>{{ coverage.sheet }} 未读、截断与未分配坐标</summary><p>未发送：{{ coverage.unread.join('，') || '无' }}</p><p>单元格值截断：{{ coverage.value_truncated.join('，') || '无' }}</p><p>超出单格预算、尚未发送：{{ coverage.deferred_large_values?.join('，') || '无' }}</p><p>当前未归入区域：{{ coverage.unassigned.join('，') || '无' }}</p><p v-if="coverage.model_unassigned">模型原始未分配：{{ coverage.model_unassigned.join('，') || '无' }}</p></details>
        <small v-if="item.status !== 'classified'">未支持：{{ item.message }}</small>
        <small v-if="analysisErrors[item.classification_id || item.name]">分析失败：{{ analysisErrors[item.classification_id || item.name] }}。</small>
        <div v-if="item.classification_id && autoSlices[item.classification_id]?.version === item.version">
          <p>自动裁切结果：未确认的区域关系请核对，下载文件保留原始数据。</p>
          <p v-for="slice in autoSlices[item.classification_id].slices" :key="slice.index">
            {{ slice.fragments.map((part) => `${part.sheet}!${part.range}`).join('、') }}
            {{ slice.basis === 'ungrouped_region' ? '（模型未确定单据归组）' : '（模型建议同一单据）' }}
            {{ slice.filename }}
            <button type="button" :disabled="busy" @click="downloadAutoSlice(item, slice)">下载裁切 Excel</button>
            <button type="button" :disabled="busy" @click="previewAutoSlice(i, slice)">用此单据生成模板</button>
          </p>
        </div>
        <div v-for="(sheet, j) in item.sheets" :key="j">
          <strong>{{ sheet.sheet }}（已读取 {{ sheet.checked_cells }} 个非空格）</strong>
          <div v-for="(region, k) in sheet.regions" :key="k" class="classification-region">
            <label><input type="radio" name="template-region" :checked="file === files[i] && selectedRegion === `${sheet.sheet} / ${region.range}`" :disabled="busy" @change="selectRegion(i, j, k)"> 选择此区域定位</label>
            <label><input v-model="selectedRows" type="checkbox" :value="`${i}:${j}:${k}`" :disabled="busy"> {{ region.range }} {{ region.parent_heading }}（边界待确认）</label>
            <small v-if="region.modified || region.label_source === 'user' || region.range_source === 'user'">用户修正</small>
            <label v-for="(label, key) in labelNames" :key="key"><input type="checkbox" :checked="region.labels.includes(key)" :disabled="busy" @change="toggleLabel(region, key, ($event.target as HTMLInputElement).checked)"> {{ label }}</label>
            <small v-if="region.evidence.length">依据：{{ region.evidence.map((e) => `${e.cell}「${e.matched}」`).join('，') }}</small>
            <small v-else>{{ region.modified ? '预筛无匹配依据，当前标签由用户修改。' : '没有匹配依据，待确认；仍可预览模板。' }}</small>
            <small v-if="region.suggested_labels?.length">模型原建议 {{ region.suggested_labels.map((label) => labelNames[label] || label).join("、") }}；</small>
            <small v-if="region.context_warning">{{ region.context_warning }}</small>
            <small v-if="region.continuation_context">参考 {{ region.continuation_context.parent_range }} 第 {{ region.continuation_context.parent_header_row }} 行与本区域第 {{ region.continuation_context.header_row }} 行的重复表头。</small>
            <small v-if="region.value_extent && !region.modified">非空格范围 {{ region.value_extent }}（仅供参考，样式、合并及说明可能在其外；未裁剪原范围）。</small>
            <small v-if="region.reason">模型解释：{{ region.reason }}（仅供核对）</small>
            <small>{{ region.dependency_status }}</small>
            <details><summary>查看表头、合并与可能的共享说明</summary>
              <label>调整区域坐标 <input :value="region.range" :disabled="busy" @input="changeRegionRange(region, sheet, ($event.target as HTMLInputElement).value)"></label>
              <small>修改后由服务端重新检查边界、重叠和合并单元格。</small>
              <p>表头：{{ region.header_cells.map((h) => `${h.cell}「${h.value}」`).join('，') || '未识别' }}</p>
              <p>合并范围：{{ region.merged_ranges.join('，') || '无' }}</p>
              <p>可能的图例或说明：{{ region.possible_shared_context.map((c) => c.cell).join('，') || '未识别' }}；关联需人工确认。</p>
              <p v-if="region.dependencies?.length">模型建议依赖：{{ region.dependencies.map((c) => `${c.sheet}!${c.cell}`).join('，') }}；需人工确认。</p>
              <template v-if="archiveOnSelect">
                <label>拆分当前片段（每行一个完整区域）<textarea v-model="region.splitDraft" :disabled="busy" rows="3" placeholder="A1:F12&#10;A13:F26"></textarea></label>
                <small>新片段须完整覆盖当前范围，不得重叠、越界或切断合并单元格。提交校验后需要重新确认续表关系，原件不变。</small>
                <button type="button" :disabled="busy || !region.splitDraft?.trim()" @click="splitRegion(item, sheet, region)">拆分此片段</button>
              </template>
            </details>
          </div>
        </div>
      </div>
      <button type="button" :disabled="!file || busy" @click="confirmClassifications">确认分类并继续</button>
      <small>预览前需确认分类；未知会保留为未知，用户可确认继续。</small>
    </div>
    </div>
    <div class="reviewed-template__step">
    <h3>第三步：清理 Excel 并保存到模板库</h3>
    <p v-for="group in classifications[files.indexOf(file as File)]?.logical_documents || []" :key="group.logical_document_id">已确认的文档片段：{{ group.fragments.map((part) => `${part.sheet}!${part.range}`).join('、') }}。</p>
    <p>从所选文档片段生成副本并提供清理建议；无法保真的跨区依赖会阻断生成。公式和不确定内容默认保留。默认不调用模型；使用模型前须明确授权文件内容发送范围。</p>
    <p>归档原件长期保留；模板生成过程中的临时副本按既有规则在 7 天后清理，已保存模板按模板库规则保留。旧记录及旧副本不会自动迁移。记录中的预览或模型输出仍可能包含表格内容。</p>
    <p v-if="file">当前文件：{{ file.name }}</p>
    <p v-if="selectedRegion">所选区域：{{ selectedRegion }}。若该区域属于已确认的多片段文档，将一起提取。</p>
    <label v-if="selectedRegion"><input v-model="selectedPrintArea" type="checkbox" :disabled="busy"> 同意在派生文件中将打印范围设为所选片段，可能超出原打印范围并包含原未打印的签字栏；原件不变，页眉页脚保留。</label>
    <label>模板名称 <input v-model="name" :disabled="busy"></label>
    <label><input v-model="initialModel" type="checkbox" :disabled="busy"> 首轮使用模型生成三个候选</label>
    <label><input v-model="sampleAuthorized" type="checkbox" :disabled="busy"> 确认此文件是获准发送的合成或公开样本，同意发送有界文本及结构概览</label>
    <label v-if="file"><input v-model="templateOwnFileAuthorized" type="checkbox" :disabled="busy"> 我有权授权当前文件 {{ file.name }} 的所选文档发送至 MiMo：最多 100 个非空单元格、每格最多 160 字，以及结构与反馈；可能包含敏感数据。</label>
    <button type="button" :disabled="!file || !classificationConfirmed || !previewSelectionReady || busy || (initialModel && sampleAuthorized === templateOwnFileAuthorized)" @click="preview()">预览清理候选</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="review">
      <p v-if="review.selected_region?.print_area_mode === 'selected'">已按您的选择设置派生打印范围：原范围 {{ review.selected_region.source_print_areas?.map((area) => area.value).join('；') || '未设置' }} → 派生范围 {{ review.selected_region.derived_print_area || '未设置' }}；原件不变。</p>
      <p>基于实际生成的候选工作簿属性的布局近似预览，不是 Excel 像素截图；公式显示表达式，未计算结果。保存时原公式缓存值会清除，需在支持计算的表格软件中打开重算。仅展示每表前 40 行、20 列和前 20 张表；超出范围请下载核对。</p>
      <label v-if="review.layout?.length">工作表 <select v-model.number="sheetIndex"><option v-for="(sheet, i) in review.layout" :key="sheet.sheet" :value="i">{{ sheet.sheet }}{{ sheet.truncated ? '（预览截断）' : '' }}</option></select></label>
      <div class="reviewed-template__previews">
        <div v-for="index in 4" :key="index" class="reviewed-template__preview">
          <strong v-if="index === 1">原件中的所选文档（派生副本）</strong>
          <label v-else><input v-model="candidateIndex" type="radio" :value="index - 2"> 模板 {{ index - 1 }}：{{ proposal.candidates[index - 2].label }}</label>
          <small v-if="index > 1 && equivalentTo(index - 2)">与模板 {{ equivalentTo(index - 2) }} 清理结果相同</small>
          <template v-if="layoutFor(index - 1)"><table><colgroup><col v-for="(width, col) in layoutFor(index - 1)!.widths" :key="col" :style="{ width: `${width * 7}px` }"></colgroup><tbody>
            <tr v-for="(row, rowIndex) in layoutFor(index - 1)!.rows" :key="rowIndex" :style="{ height: `${row.height * 1.333}px` }">
              <td v-for="cell in row.cells" :key="cell.cell" :rowspan="cell.rowspan" :colspan="cell.colspan" :style="cellStyle(cell)">{{ cell.value }}</td>
            </tr></tbody></table></template>
          <small v-else>此版本无成品布局预览，请重新生成后核对。</small>
          <button v-if="index > 1 && proposal.result_previews?.[index - 2]" type="button" :disabled="busy" @click="downloadCandidate(index - 2)">下载候选核对</button>
          <details v-if="index > 1"><summary>查看差异与理由</summary><p>{{ proposal.candidates[index - 2].explanation }}</p><p>清除 {{ proposal.candidates[index - 2].clear.length }} 格；不确定内容保留。{{ proposal.candidates[index - 2].clear.length ? '' : '与原件相同，待确认。' }}</p></details>
        </div>
      </div>
      <p>版本 {{ selectedVersion + 1 }} · {{ proposal.model.status === 'returned' ? '模型已返回建议，尚待用户确认' : proposal.model.status === 'unavailable' ? '模型不可用，显示确定性规则建议' : '确定性规则建议，未调用模型' }}<span v-if="proposal.model.status === 'returned'"> · 输入 {{ proposal.model.cells_sent }}/{{ proposal.model.cells_total }} 格{{ proposal.model.truncated ? '（已截断）' : '' }}</span></p>
      <details v-if="proposal.model.input_summary"><summary>查看模型输入摘要及来源坐标（不含正文）</summary><pre>{{ JSON.stringify(proposal.model.input_summary, null, 2) }}</pre></details>
      <details v-if="proposal.model.input_messages"><summary>历史记录中的模型输入正文（旧记录未自动清理）</summary><pre>{{ JSON.stringify(proposal.model.input_messages, null, 2) }}</pre></details>
      <button v-for="(_, index) in proposals" :key="index" type="button" :disabled="busy || selectedVersion === index" @click="switchVersion(index)">查看版本 {{ index + 1 }}</button>
      <label>自然语言修改建议 <input v-model="feedback" :disabled="busy" placeholder="例如：保留客户信息，清理产品明细"></label>
      <label><input v-model="consent" type="checkbox" :disabled="busy"> 同意向已配置模型发送最多 100 个非空单元格的文本样本及修改要求（单格最多 160 字）</label>
      <button type="button" :disabled="busy || selectedVersion !== proposals.length - 1 || !consent || sampleAuthorized === templateOwnFileAuthorized || !feedback.trim()" @click="refine">生成新一轮三个模板</button>
      <p>服务端保留 {{ proposals.length }} 个提案版本；历史版本仅供查看，保存和修改需使用最新版本。</p>
      <label><input v-model="publishToTenant" type="checkbox" :disabled="busy"> 确认发布清理后的文件到企业共享模板库；请检查是否仍有不应共享的信息。原件和审阅记录仍为私有。</label>
      <button type="button" :disabled="!name.trim() || !publishToTenant || busy || selectedVersion !== proposals.length - 1 || proposal.result_previews?.length !== 3" @click="save">保存所选模板</button>
    </div>
    <p v-if="savedId">已保存到模板库。{{ savedModelStatus }} 可再次预览当前原件并保存新模板，已有模板不会被覆盖。<button type="button" :disabled="busy" @click="download(savedId)">下载清理后的模板</button></p>
    </div>
  </section>
</template>

<style scoped>
.reviewed-template {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  border: 1px solid #d9e0e8;
  border-radius: 12px;
  margin: 1rem 0;
  background: #fff;
  min-width: 0;
}
.reviewed-template__step {
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  padding: 1rem 1.1rem;
  border: 1px solid #e4ebf3;
  border-radius: 10px;
  background: #f8fafc;
  min-width: 0;
}
.reviewed-template__step h3 {
  margin: 0 0 0.25rem;
  font-size: 1rem;
  color: #16355f;
}
.reviewed-template__step > p,
.reviewed-template__limits {
  margin: 0;
  color: #5f6f7e;
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.reviewed-template__step > label,
.reviewed-template__step .classification-results > label,
.classification-region > label {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  margin: 0;
  padding: 0.35rem 0;
  line-height: 1.45;
  overflow-wrap: anywhere;
}
.reviewed-template__step > label input[type="checkbox"],
.reviewed-template__step > label input[type="radio"],
.classification-results > label input[type="checkbox"],
.classification-region > label input[type="checkbox"],
.classification-region > label input[type="radio"] {
  flex: 0 0 auto;
  margin-top: 0.2rem;
}
.reviewed-template__step > label input[type="text"],
.reviewed-template__step > label input:not([type]),
.reviewed-template__step input[type="file"],
.reviewed-template__step input[type="number"],
.reviewed-template__step select {
  display: block;
  width: min(100%, 28rem);
  max-width: 100%;
  margin-top: 0.25rem;
  box-sizing: border-box;
}
.reviewed-template__step > button,
.reviewed-template__step .classification-results > button {
  align-self: flex-start;
  margin: 0.15rem 0;
}
.reviewed-template__step details {
  margin: 0.25rem 0;
  padding: 0.5rem 0.75rem;
  border: 1px dashed #d5deea;
  border-radius: 8px;
  background: #fff;
}
.classification-results,
.classification-region {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  min-width: 0;
}
.classification-region {
  padding: 0.65rem 0.75rem;
  border: 1px solid #e4ebf3;
  border-radius: 8px;
  background: #fff;
}
.reviewed-template__previews {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
  gap: 0.6rem;
  overflow-x: auto;
}
.reviewed-template__preview {
  border: 1px solid #d9e0e8;
  border-radius: 8px;
  padding: 0.5rem;
  max-height: 16rem;
  overflow: auto;
  overflow-wrap: anywhere;
  background: #fff;
}
.reviewed-template__preview small { display: block; }
.reviewed-template__preview table { border-collapse: collapse; table-layout: fixed; }
.reviewed-template__preview td { border: 1px solid #ddd; white-space: pre-wrap; min-width: 24px; font-size: 11px; }
.reviewed-template__cells { max-height: 25rem; overflow: auto; display: grid; gap: 0.4rem; margin: 0.8rem 0; }
.reviewed-template__cells label { display: block; overflow-wrap: anywhere; }
@media (max-width: 720px) {
  .reviewed-template,
  .reviewed-template__step {
    padding: 0.75rem;
  }
  .reviewed-template__previews {
    grid-template-columns: 1fr;
  }
}
</style>
