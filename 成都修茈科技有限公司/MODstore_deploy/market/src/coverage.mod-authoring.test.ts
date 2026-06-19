import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { useModAuthoring } from './features/mod-authoring/composables/useModAuthoring'

const modMocks = vi.hoisted(() => ({
  detail: null as any,
  summary: null as any,
  api: {
    getMod: vi.fn(),
    getModAuthoringSummary: vi.fn(),
    getModFile: vi.fn(),
    listWorkflows: vi.fn(),
    listModSnapshots: vi.fn(),
    captureModSnapshot: vi.fn(),
    restoreModSnapshot: vi.fn(),
    bumpModManifestPatchVersion: vi.fn(),
    putModManifest: vi.fn(),
    regenerateModFrontend: vi.fn(),
    putModFile: vi.fn(),
    refineSystemPrompt: vi.fn(),
    listEmployees: vi.fn(),
    listV1Packages: vi.fn(),
    catalog: vi.fn(),
    modWorkflowLink: vi.fn(),
    runWorkflowEmployeeClosure: vi.fn(),
    patchModWorkflowEmployeeNodes: vi.fn(),
    registerWorkflowEmployeeCatalog: vi.fn(),
    scaffoldWorkflowEmployee: vi.fn(),
  },
}))

vi.mock('@/api', () => ({ api: modMocks.api }))

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T
}

function makeManifest() {
  return {
    name: '覆盖行业助手',
    description: '一句话介绍',
    version: '1.0.0',
    artifact: 'employee_pack',
    kind: 'employee_pack',
    backend: { entry: 'blueprints.py' },
    config: { frontend_spec: 'config/frontend_spec.json' },
    industry: { id: '通用', name: '通用' },
    frontend: {
      pro_entry_path: 'frontend/views/HomeView.vue',
      menu: [{ label: '旧菜单', path: 'frontend/views/HomeView.vue' }],
      shell: { settings: {} },
    },
    menu_overrides: [{ key: 'old' }],
    employee_config_v2: {
      metadata: {
        suggested_skills: [{ name: '报价', brief: '生成报价' }],
        suggested_pricing: { tier: 'pro', cny: 99, period: 'month', reasoning: '高频' },
      },
      cognition: { agent: { system_prompt: '你是行业助手' } },
    },
    workflow_employees: [
      {
        id: 'sales',
        label: '销售',
        panel_title: '销售员工',
        panel_summary: '负责报价、跟进和客户沟通。'.repeat(20),
        workflow_id: 9,
      },
    ],
  }
}

function makeDetail() {
  return {
    id: 'mod-1',
    manifest: makeManifest(),
    files: [
      'manifest.json',
      'backend/__init__.py',
      'backend/blueprints.py',
      'frontend/routes.js',
      'config/ai_blueprint.json',
      'frontend/views/HomeView.vue',
    ],
    employee_readiness: {
      summary: { total: 1, ready: 1 },
      gaps: ['缺少描述'],
      employees: [{ index: 0, ready: true, gaps: [] }],
    },
  }
}

async function settle() {
  for (let i = 0; i < 8; i++) {
    await nextTick()
    await Promise.resolve()
  }
}

function wireApi() {
  const api = modMocks.api
  for (const fn of Object.values(api)) fn.mockReset()
  api.getMod.mockImplementation(async () => clone(modMocks.detail))
  api.getModAuthoringSummary.mockImplementation(async () => clone(modMocks.summary))
  api.getModFile.mockImplementation(async (_modId: string, path: string) => {
    if (path === 'config/ai_blueprint.json') {
      return {
        content: JSON.stringify({
          industry_card: { name: '零售', scenario: '门店经营' },
          api_summary: { nodes: [{ id: 'api-1' }], warnings: ['w1'] },
          workflow_sandbox: { ok: true, reports: [{ id: 'r1' }] },
          mod_sandbox: { ok: false, checks: [{ name: 'check' }] },
          vibe_heal: { ok: true },
          vibe_index: { indexed: 2 },
          frontend_app: { title: '前端应用', mod_name: '前端应用' },
        }),
      }
    }
    return { content: `content:${path}` }
  })
  api.listWorkflows.mockResolvedValue([{ id: 9, name: '报价流' }, { id: 10, name: '售后流' }])
  api.listModSnapshots.mockResolvedValue({ snapshots: [{ id: 'snap-1', ts: 1710000000, label: '初始' }] })
  api.captureModSnapshot.mockResolvedValue({ ok: true })
  api.restoreModSnapshot.mockResolvedValue({ ok: true })
  api.bumpModManifestPatchVersion.mockResolvedValue({ manifest: { version: '1.0.1' }, warnings: ['minor'] })
  api.putModManifest.mockImplementation(async (_modId: string, manifest: any) => {
    modMocks.detail.manifest = clone(manifest)
    return { warnings: ['saved-warning'] }
  })
  api.regenerateModFrontend.mockResolvedValue({ frontend_spec: { title: '新前端' } })
  api.putModFile.mockResolvedValue({ manifest_warnings: ['file-warning'] })
  api.refineSystemPrompt.mockResolvedValue({ improved_prompt: '优化后的提示词', diff_explanation: '更清楚' })
  api.listEmployees.mockResolvedValue([{ id: 'sql-employee', name: 'SQL员工', description: 'sql desc' }])
  api.listV1Packages.mockResolvedValue({ packages: [{ id: 'pkg-employee', name: '包员工', version: '1.0.0', description: 'pkg desc' }] })
  api.catalog.mockResolvedValue({ items: [{ pkg_id: 'cat-employee', name: '市场员工', version: '2.0.0', description: 'cat desc' }] })
  api.modWorkflowLink.mockResolvedValue({ manifest_warnings: ['linked'] })
  api.runWorkflowEmployeeClosure.mockResolvedValue({ ok: true, pack_register: { errors: [] }, readiness_after: { gaps: [] } })
  api.patchModWorkflowEmployeeNodes.mockResolvedValue({ employee_readiness: { ok: true }, graph_patch: { patches: [] } })
  api.registerWorkflowEmployeeCatalog.mockResolvedValue({ package: { id: 'sales', version: '1.0.0' }, employee_readiness: { employees: [{ index: 0, gaps: [] }] } })
  api.scaffoldWorkflowEmployee.mockResolvedValue({ merge_hint: 'merge this', merged_blueprint: true })
}

function createSubject(query: Record<string, unknown> = {}, params: Record<string, unknown> = { modId: 'mod-1' }) {
  const route = reactive({ params, query }) as any
  const router = { push: vi.fn() } as any
  const state = useModAuthoring(route, router)
  return { route, router, state }
}

beforeEach(() => {
  vi.useFakeTimers()
  localStorage.clear()
  sessionStorage.clear()
  modMocks.detail = makeDetail()
  modMocks.summary = {
    employee_readiness: { summary: { total: 2, ready: 1 }, gaps: ['summary gap'], employees: [{ index: 0, ready: false, gaps: ['x'] }] },
  }
  wireApi()
  Object.defineProperty(window, 'prompt', { configurable: true, value: vi.fn(() => '请优化') })
  Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => undefined) } })
})

afterEach(() => {
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('coverage mod authoring composable', () => {
  it('loads detail and exposes guide computed state', async () => {
    const { state } = createSubject({ mode: 'edit' })
    await settle()
    expect(state.loading.value).toBe(false)
    expect(state.tab.value).toBe('snapshots')
    expect(state.modId.value).toBe('mod-1')
    expect(state.modDescriptionLine.value).toBe('一句话介绍')
    expect(state.readinessSummaryLabel.value).toBe('1/1 可工作')
    expect(state.employeeReadinessGaps.value).toEqual(['缺少描述'])
    expect(state.workflowEmployeesRows.value[0].title).toBe('销售')
    expect(state.workflowEmployeesRows.value[0].bodyShort).toContain('负责报价')
    expect(state.frontendConfigPath.value).toBe('config/frontend_spec.json')
    expect(state.frontendEntryPath.value).toBe('frontend/views/HomeView.vue')
    expect(state.frontendSpecTitle.value).toBe('前端应用')
    expect(state.frontendSpecPreview.value).toContain('前端应用')
    expect(state.suggestedSkills.value[0].name).toBe('报价')
    expect(state.suggestedPricing.value?.cny).toBe(99)
    expect(state.industryCard.value?.name).toBe('零售')
    expect(state.manifestSidebarStatus.value.menuCount).toBe(1)
    expect(state.apiSummary.value.warnings).toEqual(['w1'])
    expect(state.workflowSandboxRows.value).toHaveLength(1)
    expect(state.workflowSandboxOk.value).toBe(true)
    expect(state.modSandboxChecks.value).toHaveLength(1)
    expect(state.modSandboxOk.value).toBe(false)
    expect(state.vibeHealReport.value?.ok).toBe(true)
    expect(state.vibeIndexReport.value?.indexed).toBe(2)
    expect(state.sortedFiles.value).toContain('manifest.json')
    expect(state.checklist.value.every((row) => row.ok)).toBe(true)
    expect(state.artifactNote.value).toContain('employee_pack')
    expect(state.backendEntryRel.value).toBe('backend/blueprints.py')
    expect(state.fileSet.value.has('manifest.json')).toBe(true)
    expect(state.formatSnapTime(1710000000)).not.toBe('—')
    expect(state.formatSnapTime('bad')).toBe('—')
  })

  it('covers manifest, prompt, industry and frontend/file save actions', async () => {
    const { state } = createSubject()
    await settle()

    state.applyPricingSuggestion()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('建议定价'))

    await state.handleRefineSystemPrompt()
    expect(modMocks.api.refineSystemPrompt).toHaveBeenCalledWith(expect.objectContaining({ current_prompt: '你是行业助手' }))
    expect(state.refinePromptDiff.value).toBe('更清楚')

    state.selectedIndustryPreset.value = state.industryPresetList[0].id
    await state.applyIndustryPresetToManifest()
    expect(modMocks.api.putModManifest).toHaveBeenCalled()

    state.manifestText.value = '{bad json'
    await state.saveManifest()
    expect(state.message.value).toContain('JSON 解析失败')
    state.manifestText.value = JSON.stringify(modMocks.detail.manifest)
    await state.saveManifest({ successMessage: '保存成功', flashDurationMs: 20 })
    expect(modMocks.api.putModManifest).toHaveBeenCalled()

    state.frontendBrief.value = '生成门店页面'
    await state.regenerateFrontend()
    expect(modMocks.api.regenerateModFrontend).toHaveBeenCalledWith('mod-1', '生成门店页面')
    expect(state.selectedPath.value).toBe('frontend/views/HomeView.vue')

    state.selectedPath.value = 'frontend/views/HomeView.vue'
    state.onPathSelect()
    expect(state.fileContent.value).toBe('')
    await state.loadSelectedFile()
    expect(state.fileContent.value).toContain('frontend/views/HomeView.vue')
    state.fileContent.value = 'updated'
    await state.saveFile()
    expect(modMocks.api.putModFile).toHaveBeenCalledWith('mod-1', 'frontend/views/HomeView.vue', 'updated')
    expect(modMocks.api.putModFile).toHaveBeenCalled()

    state.nameDraft.value = ''
    await expect(state.saveDescriptionFromWizard()).resolves.toBe(false)
    state.nameDraft.value = '新名称'
    state.descriptionDraft.value = '新介绍'
    state.manifestText.value = JSON.stringify(modMocks.detail.manifest)
    await expect(state.saveDescriptionFromWizard()).resolves.toBe(true)
    expect(modMocks.api.putModManifest).toHaveBeenCalled()
  })

  it('covers employee pick modal and workflow employee mutations', async () => {
    const { router, state } = createSubject()
    await settle()

    await state.openEmployeePickModal()
    expect(state.empPickRows.value.map((r) => r.id)).toEqual(expect.arrayContaining(['sql-employee', 'pkg-employee', 'cat-employee']))
    await state.confirmPickEmployee(state.empPickRows.value[0])
    expect(modMocks.api.putModManifest).toHaveBeenCalled()

    await state.openEmployeePickModal()
    state.goMyEmployees()
    expect(router.push).toHaveBeenCalledWith({ name: 'workbench-unified', query: { focus: 'employee' } })

    state.openEmployeeModal('add')
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toContain('显示名')
    state.empDraft.value = { id: 'new-emp', label: '新员工', panel_title: '新员工标题', panel_summary: '摘要' }
    await state.submitEmployeeModal()
    expect(modMocks.api.putModManifest).toHaveBeenCalled()

    state.openEmployeeModal('add')
    state.empDraft.value = { id: 'router-emp', label: '路由员工', panel_title: '', panel_summary: '' }
    state.empScaffoldRouter.value = true
    await state.submitEmployeeModal()
    expect(modMocks.api.scaffoldWorkflowEmployee).toHaveBeenCalledWith('mod-1', expect.objectContaining({ id: 'router-emp' }))
    expect(state.empModalMergeHint.value).toBe('merge this')
    state.copyMergeHint()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('merge this')

    state.openEmployeeModal('edit', 0)
    state.empDraft.value.label = '销售改名'
    await state.submitEmployeeModal()
    expect(modMocks.api.putModManifest).toHaveBeenCalled()
    await state.confirmDeleteEmployee(0)
    expect(window.confirm).toHaveBeenCalled()

    const row = state.workflowEmployeesRows.value[0] || { index: 0, bodyFull: 'body', raw: {}, title: '员工', id: 'sales' }
    state.goEmployeePrefill(row)
    expect(sessionStorage.getItem('modstore_employee_prefill')).toContain('mod-1')
    expect(router.push).toHaveBeenCalledWith({ name: 'workbench-employee' })
  })

  it('covers workflow link, closure, catalog registration and snapshot branches', async () => {
    const { router, state } = createSubject()
    await settle()

    state.openWorkflowSandboxDecompose({ linkedWorkflowId: 0 })
    expect(state.messageOk.value).toBe(false)
    state.openWorkflowSandboxDecompose({ linkedWorkflowId: 9 })
    expect(router.push).toHaveBeenCalledWith({ name: 'workbench-workflow', query: { edit: '9', tab: 'sandbox' } })

    await state.applyWorkflowLinkToRow({ index: 0 })
    expect(state.message.value).toContain('下拉框')
    state.linkPick[0] = 10
    await state.applyWorkflowLinkToRow({ index: 0 })
    expect(modMocks.api.modWorkflowLink).toHaveBeenCalledWith('mod-1', { workflow_id: 10, workflow_index: 0 })
    expect(modMocks.api.modWorkflowLink).toHaveBeenCalled()

    await state.runWorkflowEmployeeClosure()
    expect(state.message.value).toContain('请先登录')
    localStorage.setItem('modstore_token', 'token')
    await state.runWorkflowEmployeeClosure()
    expect(modMocks.api.runWorkflowEmployeeClosure).toHaveBeenCalledWith('mod-1', expect.objectContaining({ register_missing: true }))

    await state.patchWorkflowEmployeeNodesRetry()
    expect(modMocks.api.patchModWorkflowEmployeeNodes).toHaveBeenCalledWith('mod-1')
    await state.registerWorkflowEmployeeCatalog({ index: 0 })
    expect(modMocks.api.registerWorkflowEmployeeCatalog).toHaveBeenCalledWith('mod-1', 0)

    await state.refreshSnapshots()
    expect(state.snapshotsRows.value).toHaveLength(1)
    state.snapshotLabelDraft.value = '手动快照'
    await state.captureSnapshotManual()
    expect(modMocks.api.captureModSnapshot).toHaveBeenCalledWith('mod-1', '手动快照')
    await state.restoreSnapshot('snap-1')
    expect(modMocks.api.restoreModSnapshot).toHaveBeenCalledWith('mod-1', 'snap-1')
    await state.bumpManifestPatch()
    expect(modMocks.api.bumpModManifestPatchVersion).toHaveBeenCalledWith('mod-1')

    modMocks.api.listModSnapshots.mockRejectedValueOnce(Object.assign(new Error('not found'), { status: 404 }))
    await state.refreshSnapshots()
    expect(state.snapshotsLoadErr.value).toBe('')
    modMocks.api.listModSnapshots.mockRejectedValueOnce(new Error('snapshot boom'))
    await state.refreshSnapshots()
    expect(state.snapshotsLoadErr.value).toBe('snapshot boom')

    state.goRepo()
    expect(router.push).toHaveBeenCalledWith({ name: 'workbench-repository' })
    await state.refreshSummary()
    expect(modMocks.api.getModAuthoringSummary).toHaveBeenCalled()
  })

  it('covers load and API failure fallbacks', async () => {
    modMocks.api.getMod.mockRejectedValueOnce(new Error('load failed'))
    const { state } = createSubject()
    await settle()
    expect(state.loadError.value).toBe('load failed')

    state.flash('manual error', false, 10)
    expect(state.message.value).toBe('manual error')
    vi.advanceTimersByTime(11)
    expect(state.message.value).toBe('')

    modMocks.api.listEmployees.mockRejectedValueOnce(new Error('employees failed'))
    modMocks.api.listV1Packages.mockRejectedValueOnce(new Error('packages failed'))
    modMocks.api.catalog.mockRejectedValueOnce(new Error('catalog failed'))
    await state.openEmployeePickModal()
    expect(state.empPickRows.value).toEqual([])
  })

  it('covers computed fallback states and prompt/pricing edge branches', async () => {
    const detail = makeDetail()
    delete (detail as any).employee_readiness
    delete (detail.manifest as any).workflow_employees
    delete (detail.manifest as any).config
    delete (detail.manifest as any).frontend
    ;(detail.manifest as any).artifact = 'bundle'
    ;(detail.manifest as any).employee_config_v2 = { metadata: { suggested_pricing: { tier: 'team', cny: 199, period: 'year' } } }
    detail.files = []
    modMocks.detail = detail
    modMocks.summary = null
    modMocks.api.getModFile.mockResolvedValueOnce({
      content: JSON.stringify({
        industry: { name: '餐饮', scenario: '翻台' },
        workflow_sandbox: null,
        mod_sandbox: null,
        vibe_heal: null,
        vibe_index: null,
      }),
    })
    const { state } = createSubject()
    await settle()

    expect(state.readinessSummaryLabel.value).toBe('无员工')
    expect(state.employeeReadinessGaps.value).toEqual([])
    expect(state.workflowEmployeesRows.value).toEqual([])
    expect(state.frontendConfigPath.value).toBe('config/frontend_spec.json')
    expect(state.frontendEntryPath.value).toBe('')
    expect(state.frontendSpecTitle.value).toBe('')
    expect(state.frontendSpecPreview.value).toBe('')
    expect(state.suggestedSkills.value).toEqual([])
    expect(state.industryCard.value).toBeNull()
    expect(state.workflowSandboxRows.value).toEqual([])
    expect(state.workflowSandboxOk.value).toBe(false)
    expect(state.modSandboxChecks.value).toEqual([])
    expect(state.modSandboxOk.value).toBe(false)
    expect(state.vibeHealReport.value).toBeNull()
    expect(state.vibeIndexReport.value).toBeNull()
    expect(state.fileSet.value.size).toBe(0)
    expect(state.sortedFiles.value).toEqual([])
    expect(state.artifactNote.value).toBe('类型：bundle')
    expect(state.checklist.value.some((row) => !row.ok)).toBe(true)
    expect(state.selectedIndustryScenario.value).toBeTruthy()

    modMocks.detail.files = ['config/ai_blueprint.json']
    await state.reload()
    expect(state.industryCard.value?.name).toBe('餐饮')

    await state.handleRefineSystemPrompt()
    expect(state.message.value).toContain('system_prompt')

    Object.defineProperty(window, 'prompt', { configurable: true, value: vi.fn(() => '   ') })
    ;(modMocks.detail.manifest as any).employee_config_v2 = { cognition: { agent: { system_prompt: '旧提示' } } }
    await state.reload()
    await state.handleRefineSystemPrompt()
    expect(modMocks.api.refineSystemPrompt).not.toHaveBeenCalled()

    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: vi.fn(async () => Promise.reject(new Error('denied'))) } })
    ;(modMocks.detail.manifest as any).employee_config_v2 = {
      metadata: { suggested_pricing: { tier: 'once', cny: 9, period: 'once' } },
    }
    await state.reload()
    state.applyPricingSuggestion()
    await settle()
    expect(state.message.value).toContain('建议定价')

    state.manifestText.value = '{bad json'
    await state.applyIndustryPresetToManifest()
    expect(state.message.value).toContain('JSON 解析失败')
  })

  it('covers prompt, employee picker, workflow and catalog failure branches', async () => {
    const { state } = createSubject()
    await settle()

    Object.defineProperty(window, 'prompt', { configurable: true, value: vi.fn(() => '优化') })
    modMocks.api.refineSystemPrompt.mockResolvedValueOnce({})
    await state.handleRefineSystemPrompt()
    expect(state.refinePromptError.value).toContain('未收到优化结果')

    ;(modMocks.detail.manifest as any).employee_config_v2 = { cognition: { agent: { system_prompt: '旧提示' } } }
    modMocks.api.refineSystemPrompt.mockResolvedValueOnce({ improved_prompt: '补齐嵌套结构', diff_explanation: '' })
    await state.reload()
    await state.handleRefineSystemPrompt()
    expect(modMocks.api.putModManifest).toHaveBeenCalledWith('mod-1', expect.objectContaining({ employee_config_v2: expect.any(Object) }))

    await state.openEmployeePickModal()
    const catRow = state.empPickRows.value.find((row) => row.id === 'cat-employee')
    expect(catRow).toBeTruthy()
    await state.confirmPickEmployee(catRow)
    expect(modMocks.api.putModManifest).toHaveBeenCalled()

    state.empPickSaving.value = true
    await state.confirmPickEmployee({ id: 'skip', name: '跳过' })
    state.empPickSaving.value = false

    modMocks.api.putModManifest.mockRejectedValueOnce(new Error('pick failed'))
    await state.confirmPickEmployee({ id: 'manual-employee', name: '', sourceLabel: '手动来源' })
    expect(state.empPickError.value).toContain('pick failed')

    localStorage.setItem('modstore_token', 'token')
    modMocks.api.runWorkflowEmployeeClosure.mockResolvedValueOnce({
      ok: false,
      pack_register: { errors: ['register failed'] },
      readiness_after: { gaps: ['缺少路由'] },
    })
    await state.runWorkflowEmployeeClosure()
    expect(state.message.value).toContain('登记有 1 项失败')

    modMocks.api.runWorkflowEmployeeClosure.mockRejectedValueOnce(Object.assign(new Error('gone'), { status: 404 }))
    await state.runWorkflowEmployeeClosure()
    expect(state.message.value).toContain('接口未就绪')

    modMocks.api.runWorkflowEmployeeClosure.mockRejectedValueOnce(new Error('closure boom'))
    await state.runWorkflowEmployeeClosure()
    expect(state.message.value).toBe('closure boom')

    modMocks.api.patchModWorkflowEmployeeNodes.mockResolvedValueOnce({
      employee_readiness: { gaps: ['还缺 system prompt'] },
      graph_patch: { patches: [{ error: 'node bad' }] },
    })
    await state.patchWorkflowEmployeeNodesRetry()
    expect(state.message.value).toContain('修图部分失败')

    modMocks.api.patchModWorkflowEmployeeNodes.mockResolvedValueOnce({
      employee_readiness: { gaps: ['缺少包登记'] },
      graph_patch: { patches: [{ skipped: '已跳过重复节点' }] },
    })
    await state.patchWorkflowEmployeeNodesRetry()
    expect(state.message.value).toContain('仍有缺口')

    modMocks.api.patchModWorkflowEmployeeNodes.mockRejectedValueOnce(new Error('patch boom'))
    await state.patchWorkflowEmployeeNodesRetry()
    expect(state.message.value).toBe('patch boom')

    modMocks.api.registerWorkflowEmployeeCatalog.mockResolvedValueOnce({
      package: {},
      employee_readiness: { employees: [{ index: 0, gaps: ['补齐描述'] }] },
    })
    await state.registerWorkflowEmployeeCatalog({ index: 0 })
    expect(state.message.value).toContain('/v1/packages')
    expect(state.message.value).toContain('补齐描述')

    modMocks.api.registerWorkflowEmployeeCatalog.mockRejectedValueOnce(new Error('catalog boom'))
    await state.registerWorkflowEmployeeCatalog({ index: 0 })
    expect(state.message.value).toBe('catalog boom')
  })

  it('covers employee modal validation, scaffold, delete and persist errors', async () => {
    const { state } = createSubject()
    await settle()

    state.openEmployeeModal('add')
    state.empDraft.value = { id: '', label: '缺 ID', panel_title: '', panel_summary: '' }
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toContain('内部 ID')

    state.empDraft.value = { id: 'Bad ID', label: '坏 ID', panel_title: '', panel_summary: '' }
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toContain('内部 ID 须')

    state.empDraft.value = { id: 'sales', label: '重复', panel_title: '', panel_summary: '' }
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toContain('已存在')

    modMocks.api.scaffoldWorkflowEmployee.mockResolvedValueOnce({ merged_blueprint: false })
    state.empDraft.value = { id: 'router_empty_hint', label: '路由无提示', panel_title: '', panel_summary: '' }
    state.empScaffoldRouter.value = true
    await state.submitEmployeeModal()
    expect(state.empModalOpen.value).toBe(false)

    state.openEmployeeModal('add')
    modMocks.api.scaffoldWorkflowEmployee.mockRejectedValueOnce(new Error('scaffold boom'))
    state.empDraft.value = { id: 'router_error', label: '路由错误', panel_title: '', panel_summary: '' }
    state.empScaffoldRouter.value = true
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toBe('scaffold boom')

    state.openEmployeeModal('edit', 999)
    state.empDraft.value = { id: 'lost', label: '丢失', panel_title: '', panel_summary: '' }
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toContain('索引无效')

    state.openEmployeeModal('edit', 0)
    modMocks.api.putModManifest.mockRejectedValueOnce(new Error('persist boom'))
    state.empDraft.value.label = '保存失败'
    await state.submitEmployeeModal()
    expect(state.empModalError.value).toBe('persist boom')

    await state.confirmDeleteEmployee(-1)
    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => false) })
    await state.confirmDeleteEmployee(0)
    expect(modMocks.api.putModManifest).not.toHaveBeenLastCalledWith('mod-1', expect.objectContaining({ workflow_employees: [] }))

    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
    modMocks.api.putModManifest.mockRejectedValueOnce(new Error('delete boom'))
    await state.confirmDeleteEmployee(0)
    expect(state.message.value).toBe('delete boom')

    state.closeEmployeeModal()
    expect(state.empModalOpen.value).toBe(false)
  })

  it('covers snapshot, manifest, frontend and file API error branches', async () => {
    const { state } = createSubject()
    await settle()

    modMocks.api.listWorkflows.mockRejectedValueOnce(new Error('workflow list boom'))
    await state.reload()
    await settle()
    expect(state.linkableWorkflows.value).toEqual([])

    state.linkPick[0] = 10
    modMocks.api.modWorkflowLink.mockRejectedValueOnce(new Error('link boom'))
    await state.applyWorkflowLinkToRow({ index: 0 })
    expect(state.message.value).toBe('link boom')

    modMocks.api.listModSnapshots.mockResolvedValueOnce([{ id: 'array-snap' }])
    await state.refreshSnapshots()
    expect(state.snapshotsRows.value[0].id).toBe('array-snap')

    modMocks.api.captureModSnapshot.mockRejectedValueOnce(new Error('capture boom'))
    await state.captureSnapshotManual()
    expect(state.message.value).toBe('capture boom')

    await state.restoreSnapshot('')
    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => false) })
    await state.restoreSnapshot('snap-1')
    expect(modMocks.api.restoreModSnapshot).not.toHaveBeenLastCalledWith('mod-1', 'snap-1')

    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
    modMocks.api.restoreModSnapshot.mockRejectedValueOnce(new Error('restore boom'))
    await state.restoreSnapshot('snap-1')
    expect(state.message.value).toBe('restore boom')

    modMocks.api.bumpModManifestPatchVersion.mockResolvedValueOnce({})
    await state.bumpManifestPatch()
    expect(state.message.value).toContain('新版本')
    modMocks.api.bumpModManifestPatchVersion.mockRejectedValueOnce(new Error('bump boom'))
    await state.bumpManifestPatch()
    expect(state.message.value).toBe('bump boom')

    modMocks.api.putModManifest.mockRejectedValueOnce(new Error('manifest boom'))
    state.manifestText.value = JSON.stringify(modMocks.detail.manifest)
    await state.saveManifest()
    expect(state.message.value).toBe('manifest boom')

    modMocks.api.regenerateModFrontend.mockResolvedValueOnce({})
    state.frontendBrief.value = '不返回 spec'
    await state.regenerateFrontend()
    expect(state.message.value).toContain('前端已生成')
    modMocks.api.regenerateModFrontend.mockRejectedValueOnce(new Error('frontend boom'))
    await state.regenerateFrontend()
    expect(state.message.value).toBe('frontend boom')

    state.selectedPath.value = 'frontend/views/HomeView.vue'
    modMocks.api.getModFile.mockResolvedValueOnce({})
    await state.loadSelectedFile()
    expect(state.fileContent.value).toBe('')
    modMocks.api.getModFile.mockRejectedValueOnce(new Error('file load boom'))
    await state.loadSelectedFile()
    expect(state.message.value).toBe('file load boom')

    modMocks.api.putModFile.mockResolvedValueOnce({})
    state.fileContent.value = 'no warnings'
    await state.saveFile()
    expect(state.fileWarnings.value).toEqual([])
    modMocks.api.putModFile.mockRejectedValueOnce(new Error('file save boom'))
    await state.saveFile()
    expect(state.message.value).toBe('file save boom')

    state.descriptionDraft.value = ''
    await expect(state.saveDescriptionFromWizard()).resolves.toBe(false)
    state.descriptionDraft.value = '描述'
    state.manifestText.value = '{bad json'
    await expect(state.saveDescriptionFromWizard()).resolves.toBe(false)
  })
})
