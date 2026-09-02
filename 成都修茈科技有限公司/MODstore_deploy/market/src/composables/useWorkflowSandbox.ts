import { computed, ref, watch, nextTick, type Ref } from 'vue'
import { api } from '../api'
import { WORKFLOW_SANDBOX_PRESETS } from '../workflowSandboxPresets'
import { errMessage } from '../utils/errMessage'
import type { WorkflowSandboxResponse } from '../types/api'
import type { RealPrecheck, WorkflowDetailResponse, WorkflowEdgeRow, WorkflowNodeRow, WorkflowRow, EmployeeRow } from '../views/workflow/workflowTypes'
import {
  asRecord,
  parsePositiveInt,
  employeeIdMatches,
  workflowEmployeesFromModRow,
  employeeMatchesManifestEntry,
} from '../views/workflow/workflowSandboxHelpers'

/** WorkflowView 沙盒测试域（自 WorkflowView.vue 原样迁移） */
export function useWorkflowSandbox(deps: {
  flash: (msg: string, ok?: boolean) => void
  employees: Ref<EmployeeRow[]>
  workflows: Ref<WorkflowRow[]>
  activeTab: Ref<string>
  currentWorkflow: Ref<WorkflowRow | null>
  focusedNodeId: Ref<number>
  editWorkflow: (workflowId: number) => Promise<void>
  loadWorkflows: () => Promise<void>
  pickEmployeeNameById: (empId: unknown) => string
}) {
  const { flash, workflows, activeTab, currentWorkflow, focusedNodeId, editWorkflow, loadWorkflows } = deps
  const pickEmployeeNameById = deps.pickEmployeeNameById

  // 沙盒
  const sandboxEmployeeId = ref('')
  const sandboxWorkflowCandidates = ref<Array<{ id: number; name?: string; source?: string }>>([])
  const sandboxMappingLoading = ref(false)
  const sandboxMappingError = ref('')
  const sandboxMappingNodeHits = ref(0)
  const sandboxMappingManifestHits = ref(0)
  const sandboxWorkflowId = ref(0)
  const sandboxInputJson = ref('{\n  "topic": "示例主题"\n}')
  const sandboxLoading = ref(false)
  const sandboxAutoCreateBusy = ref(false)
  const sandboxReport = ref<WorkflowSandboxResponse | null>(null)
  const sandboxError = ref('')
  const lastRunMeta = ref<{ mode: string; startedAt: string; precheck: RealPrecheck | null }>({ mode: '', startedAt: '', precheck: null })
  /** 沙盒页展示用的服务端图快照（与画布未保存修改可能不一致） */
  const decomposeNodes = ref<WorkflowNodeRow[]>([])
  const decomposeEdges = ref<WorkflowEdgeRow[]>([])
  const decomposeLoading = ref(false)
  const sandboxPresetId = ref('topic')

  const workflowDetailCache = new Map<number, WorkflowDetailResponse>()

  const realRunDisabledReason = computed(() => {
    if (sandboxLoading.value) return '当前正在运行，请等待完成后再发起真实测试。'
    if (sandboxMappingLoading.value) return '正在构建员工到工作流映射，请稍候。'
    if (!sandboxEmployeeId.value) return '请先选择 AI 员工。'
    if (!sandboxWorkflowId.value) return '请先选择关联工作流。'
    return ''
  })

  const canRunReal = computed(() => !realRunDisabledReason.value)

  const realPrecheckSummary = computed(() => {
    const p = lastRunMeta.value?.precheck
    if (!p || lastRunMeta.value?.mode !== 'real') return ''
    if (!p.checkedCount) return '未检测到员工节点；真实测试将按图继续执行。'
    const okPart = p.ok ? '通过' : '未通过'
    return `检查${okPart}：员工节点 ${p.checkedCount} 个，缺失配置 ${p.missingConfigCount}，状态异常 ${p.statusErrorCount}。`
  })

  async function getWorkflowDetailCached(workflowId: number): Promise<WorkflowDetailResponse> {
    const cached = workflowDetailCache.get(workflowId)
    if (cached) return cached
    const detail = (await api.getWorkflow(workflowId)) as WorkflowDetailResponse
    workflowDetailCache.set(workflowId, detail)
    return detail
  }

  async function rebuildSandboxWorkflowCandidatesFallback(employeeId: string) {
    const byId = new Map<number, { id: number; name: string; source: string }>()
    const nodeHitIds = new Set<number>()
    const manifestHitIds = new Set<number>()
    const employeeName = pickEmployeeNameById(employeeId)
    for (const w of workflows.value || []) {
      let detail = null
      try {
        detail = await getWorkflowDetailCached(w.id)
      } catch {
        continue
      }
      const wsNodes = Array.isArray(detail?.nodes) ? detail.nodes : []
      const hit = wsNodes.some((n) => {
        if (n.node_type !== 'employee') return false
        const cfg = asRecord(n.config)
        return employeeIdMatches(String(cfg.employee_id || '').trim(), employeeId)
      })
      if (hit) {
        nodeHitIds.add(w.id)
        byId.set(w.id, { id: w.id, name: w.name || `工作流 ${w.id}`, source: 'node' })
      }
    }

    // 前端本地兜底：/api/mods 返回 workflow_employees 摘要，不保证携带 workflow_id。
    try {
      const modsRes = await api.listMods()
      const mods = Array.isArray(modsRes?.data) ? modsRes.data : []
      for (const mod of mods) {
        for (const entry of workflowEmployeesFromModRow(mod)) {
          if (!employeeMatchesManifestEntry(entry, employeeId, employeeName)) continue
          const entryRecord = asRecord(entry)
          const wid = parsePositiveInt(entryRecord.workflow_id ?? entryRecord.workflowId)
          if (!wid || nodeHitIds.has(wid) || manifestHitIds.has(wid)) continue
          const wf = (workflows.value || []).find((x) => x.id === wid)
          if (wf) {
            manifestHitIds.add(wid)
            byId.set(wid, { id: wf.id, name: wf.name || `工作流 ${wf.id}`, source: 'manifest' })
          }
        }
      }
    } catch {
      /* ignore */
    }

    const rows = [...byId.values()].sort((a, b) => a.id - b.id)
    return {
      rows,
      nodeHits: nodeHitIds.size,
      manifestHits: manifestHitIds.size,
    }
  }

  async function rebuildSandboxWorkflowCandidates() {
    sandboxWorkflowCandidates.value = []
    sandboxMappingError.value = ''
    sandboxMappingNodeHits.value = 0
    sandboxMappingManifestHits.value = 0
    sandboxWorkflowId.value = 0
    if (!sandboxEmployeeId.value) return
    const employeeId = String(sandboxEmployeeId.value).trim()
    sandboxMappingLoading.value = true
    try {
      let rows: Array<{ id: number; name: string; source: string }> = []
      let nodeHits = 0
      let manifestHits = 0
      try {
        const res = await api.listWorkflowsByEmployee(employeeId)
        const allRows = Array.isArray(res?.workflows) ? res.workflows : []
        rows = allRows
          .map((value: unknown) => {
            const row = asRecord(value)
            return {
              id: parsePositiveInt(row.id),
              name: String(row.name || '').trim() || `工作流 ${row.id}`,
              source: String(row.source || ''),
            }
          })
          .filter((x: { id: number }) => x.id > 0)
        nodeHits = parsePositiveInt(res?.node_hits)
        manifestHits = parsePositiveInt(res?.manifest_hits)
      } catch (e) {
        const fallback = await rebuildSandboxWorkflowCandidatesFallback(employeeId)
        rows = fallback.rows
        nodeHits = fallback.nodeHits
        manifestHits = fallback.manifestHits
        sandboxMappingError.value = `映射服务不可用，已启用本地回退：${errMessage(e)}`
      }

      sandboxWorkflowCandidates.value = rows
      sandboxMappingNodeHits.value = nodeHits
      sandboxMappingManifestHits.value = manifestHits
      if (rows.length) {
        sandboxWorkflowId.value = rows[0].id
        await loadDecomposeGraph(rows[0].id)
      }
    } catch (e) {
      sandboxMappingError.value = errMessage(e)
    } finally {
      sandboxMappingLoading.value = false
    }
  }

  async function createSandboxWorkflowForEmployee() {
    const employeeId = String(sandboxEmployeeId.value || '').trim()
    if (!employeeId) {
      flash('请先选择 AI 员工', false)
      return
    }
    if (!localStorage.getItem('modstore_token')) {
      flash('请先登录工作台（右上角登录）后再自动生成工作流', false)
      return
    }
    const employeeName = pickEmployeeNameById(employeeId) || employeeId
    sandboxAutoCreateBusy.value = true
    try {
      const isWechatPhone = employeeId === 'wechat_phone'
        || employeeId.endsWith('-wechat_phone')
        || employeeId.endsWith('_wechat_phone')

      if (isWechatPhone) {
        const created = await api.createWorkflow(
          `${employeeName} · 沙盒测试流程`,
          '自动生成：微信电话对接业务员完整业务流程（来电监控→接听→ASR→意图→TTS回灌）。',
        )
        const wid = parsePositiveInt(created?.id)
        if (!wid) throw new Error('创建工作流失败：未返回有效 workflow id')

        const nStart = await api.addWorkflowNode(wid, 'start', '开始', {}, 120, 200)
        const nMonitor = await api.addWorkflowNode(
          wid, 'employee', '监控微信来电',
          { employee_id: employeeId, task: 'monitor_incoming_call' }, 340, 200,
        )
        const nCallCond = await api.addWorkflowNode(
          wid, 'condition', '来电状态判断', {}, 560, 200,
        )
        const nAnswer = await api.addWorkflowNode(
          wid, 'employee', '自动接听',
          { employee_id: employeeId, task: 'auto_answer' }, 780, 120,
        )
        const nAsr = await api.addWorkflowNode(
          wid, 'employee', '语音采集与ASR',
          { employee_id: employeeId, task: 'asr_transcribe' }, 1000, 120,
        )
        const nIntentCond = await api.addWorkflowNode(
          wid, 'condition', '意图识别判断', {}, 1220, 120,
        )
        const nTts = await api.addWorkflowNode(
          wid, 'employee', 'TTS语音合成与回灌',
          { employee_id: employeeId, task: 'tts_playback' }, 1440, 60,
        )
        const nEnd = await api.addWorkflowNode(wid, 'end', '结束', {}, 1660, 120)

        const sid = parsePositiveInt(nStart?.id)
        const mid = parsePositiveInt(nMonitor?.id)
        const ccid = parsePositiveInt(nCallCond?.id)
        const aid = parsePositiveInt(nAnswer?.id)
        const asrid = parsePositiveInt(nAsr?.id)
        const icid = parsePositiveInt(nIntentCond?.id)
        const tid2 = parsePositiveInt(nTts?.id)
        const eid = parsePositiveInt(nEnd?.id)
        if (!sid || !mid || !ccid || !aid || !asrid || !icid || !tid2 || !eid) {
          throw new Error('初始化节点失败，请重试')
        }

        await api.addWorkflowEdge(wid, sid, mid, '')
        await api.addWorkflowEdge(wid, mid, ccid, '')
        await api.addWorkflowEdge(wid, ccid, aid, "call_state == 'ringing'")
        await api.addWorkflowEdge(wid, ccid, eid, '')
        await api.addWorkflowEdge(wid, aid, asrid, '')
        await api.addWorkflowEdge(wid, asrid, icid, '')
        await api.addWorkflowEdge(wid, icid, tid2, "intent == 'answer'")
        await api.addWorkflowEdge(wid, icid, eid, '')
        await api.addWorkflowEdge(wid, tid2, eid, '')

        sandboxPresetId.value = 'phone_wechat'
        applySandboxPreset('phone_wechat')

        workflowDetailCache.delete(wid)
        await loadWorkflows()
        await rebuildSandboxWorkflowCandidates()
        if (sandboxWorkflowCandidates.value.some((w) => w.id === wid)) {
          sandboxWorkflowId.value = wid
          await loadDecomposeGraph(wid)
        }
        flash(`已生成微信电话对接业务员测试工作流（id=${wid}，7节点9边），预设已切换到 phone_wechat`, true)
      } else {
        const created = await api.createWorkflow(`${employeeName} · 沙盒测试流程`, `自动生成：员工 ${employeeId} 的最小可测流程。`)
        const wid = parsePositiveInt(created?.id)
        if (!wid) throw new Error('创建工作流失败：未返回有效 workflow id')
        const nStart = await api.addWorkflowNode(wid, 'start', '开始', {}, 120, 180)
        const nEmp = await api.addWorkflowNode(
          wid,
          'employee',
          `${employeeName} 节点`,
          { employee_id: employeeId, task: 'analyze_document' },
          360,
          180,
        )
        const nEnd = await api.addWorkflowNode(wid, 'end', '结束', {}, 620, 180)
        const sid = parsePositiveInt(nStart?.id)
        const eid = parsePositiveInt(nEmp?.id)
        const tid = parsePositiveInt(nEnd?.id)
        if (!sid || !eid || !tid) throw new Error('初始化节点失败，请重试')
        await api.addWorkflowEdge(wid, sid, eid, '')
        await api.addWorkflowEdge(wid, eid, tid, '')
        workflowDetailCache.delete(wid)
        await loadWorkflows()
        await rebuildSandboxWorkflowCandidates()
        if (sandboxWorkflowCandidates.value.some((w) => w.id === wid)) {
          sandboxWorkflowId.value = wid
          await loadDecomposeGraph(wid)
        }
        flash(`已生成测试工作流（id=${wid}），可直接进行 Mock / 真实测试`, true)
      }
    } catch (e) {
      const msg = errMessage(e)
      if (msg.includes('缺少认证凭证') || msg.includes('无效的认证凭证') || msg.includes('401')) {
        flash('自动生成工作流失败：登录已失效，请重新登录工作台后重试', false)
        return
      }
      flash(`自动生成工作流失败：${msg}`, false)
    } finally {
      sandboxAutoCreateBusy.value = false
    }
  }

  async function loadDecomposeGraph(workflowId: number) {
    if (!workflowId) {
      decomposeNodes.value = []
      decomposeEdges.value = []
      return
    }
    decomposeLoading.value = true
    try {
      const res = await api.getWorkflow(workflowId)
      decomposeNodes.value = res.nodes || []
      decomposeEdges.value = res.edges || []
    } catch {
      decomposeNodes.value = []
      decomposeEdges.value = []
    } finally {
      decomposeLoading.value = false
    }
  }

  function applySandboxPreset(id: string) {
    const p = WORKFLOW_SANDBOX_PRESETS.find((x) => x.id === id)
    if (!p) return
    sandboxInputJson.value = JSON.stringify(p.input_data, null, 2)
  }

  function onSandboxPresetChange(ev: Event) {
    const t = ev.target as HTMLSelectElement | null
    const v = t?.value
    if (typeof v !== 'string') return
    sandboxPresetId.value = v
    applySandboxPreset(v)
  }

  async function openSandboxFor(workflowId: number) {
    const wid = parsePositiveInt(workflowId)
    if (wid > 0) {
      try {
        const detail = await getWorkflowDetailCached(wid)
        const nodes: WorkflowNodeRow[] = Array.isArray(detail?.nodes) ? (detail.nodes as WorkflowNodeRow[]) : []
        const eNode = nodes.find((n) => n?.node_type === 'employee' && n?.config?.employee_id)
        if (eNode) sandboxEmployeeId.value = String(eNode.config?.employee_id ?? '').trim()
      } catch {
        /* ignore */
      }
    }
    if (sandboxEmployeeId.value) {
      await rebuildSandboxWorkflowCandidates()
      if (sandboxWorkflowCandidates.value.some((w) => w.id === wid)) sandboxWorkflowId.value = wid
    } else {
      sandboxWorkflowId.value = wid
    }
    sandboxReport.value = null
    sandboxError.value = ''
    activeTab.value = 'sandbox'
    await loadDecomposeGraph(sandboxWorkflowId.value)
  }

  function parseSandboxInput() {
    const raw = (sandboxInputJson.value || '').trim()
    if (!raw) return {}
    try {
      const o = JSON.parse(raw)
      return typeof o === 'object' && o !== null && !Array.isArray(o) ? o : {}
    } catch (e: unknown) {
      throw new Error('运行变量须为合法 JSON 对象: ' + errMessage(e))
    }
  }

  async function runSandboxValidate() {
    await runSandbox('validate')
  }

  async function runSandbox(mode: 'validate' | 'mock' | 'real') {
    if (!sandboxWorkflowId.value) {
      flash('请先选择员工和关联工作流', false)
      return
    }
    sandboxLoading.value = true
    sandboxError.value = ''
    sandboxReport.value = null
    lastRunMeta.value = {
      mode,
      startedAt: new Date().toISOString(),
      precheck: mode === 'real' ? (lastRunMeta.value?.precheck || null) : null,
    }
    try {
      const input = parseSandboxInput()
      const validateOnly = mode === 'validate'
      const mockEmployees = mode !== 'real'
      const report = await api.workflowSandboxRun(sandboxWorkflowId.value, {
        input_data: input,
        mock_employees: mockEmployees,
        validate_only: validateOnly,
      })
      sandboxReport.value = report
      if (validateOnly) {
        flash(report.ok ? '校验通过' : '校验未通过', report.ok)
      } else if (mode === 'real') {
        flash('真实测试完成', true)
      } else {
        flash('Mock 测试完成', true)
      }
    } catch (e: unknown) {
      sandboxError.value = errMessage(e)
      flash(sandboxError.value, false)
      if (mode === 'real') {
        await autoLocateLikelyEmployeeNode()
      }
    } finally {
      sandboxLoading.value = false
    }
  }

  async function runSandboxMock() {
    await runSandbox('mock')
  }

  async function runSandboxReal() {
    if (!canRunReal.value) {
      if (realRunDisabledReason.value) flash(realRunDisabledReason.value, false)
      return
    }
    const pre = await runRealPrecheck(sandboxWorkflowId.value)
    lastRunMeta.value = {
      mode: 'real',
      startedAt: new Date().toISOString(),
      precheck: pre,
    }
    if (!pre.ok) {
      const first = pre.issues[0] || '真实测试前置检查未通过'
      sandboxError.value = first
      flash(`真实测试已阻断：${first}`, false)
      await autoLocateLikelyEmployeeNode(pre.nodeIds || [])
      return
    }
    await runSandbox('real')
  }

  async function runRealPrecheck(workflowId: number) {
    const detail = await getWorkflowDetailCached(workflowId)
    const wsNodes: WorkflowNodeRow[] = Array.isArray(detail?.nodes) ? (detail.nodes as WorkflowNodeRow[]) : []
    const empNodes = wsNodes.filter((n) => n && n.node_type === 'employee')
    const issues: string[] = []
    const missingConfig: string[] = []
    const statusErrors: string[] = []
    const issueNodeIds: number[] = []
    for (const n of empNodes) {
      const cfg = n && typeof n.config === 'object' ? n.config : {}
      const eid = String(cfg.employee_id || '').trim()
      if (!eid) {
        missingConfig.push(`节点「${n.name || n.id}」缺少 employee_id`)
        issueNodeIds.push(parsePositiveInt(n.id))
        continue
      }
      try {
        const st = await api.getEmployeeStatus(eid)
        if (!st || st.status === 'not_found') {
          statusErrors.push(`员工 ${eid} 不存在或未加载到执行器目录`)
          issueNodeIds.push(parsePositiveInt(n.id))
        } else if (typeof st.status === 'string' && st.status.toLowerCase() !== 'active') {
          statusErrors.push(`员工 ${eid} 状态异常：${st.status}`)
          issueNodeIds.push(parsePositiveInt(n.id))
        }
      } catch (e: unknown) {
        statusErrors.push(`员工 ${eid} 状态检查失败：${errMessage(e)}`)
        issueNodeIds.push(parsePositiveInt(n.id))
      }
    }
    issues.push(...missingConfig, ...statusErrors)
    return {
      ok: issues.length === 0,
      checkedCount: empNodes.length,
      missingConfigCount: missingConfig.length,
      statusErrorCount: statusErrors.length,
      nodeIds: issueNodeIds.filter((x) => x > 0),
      issues,
    }
  }

  async function autoLocateLikelyEmployeeNode(preferredNodeIds: number[] = []) {
    const targetWorkflowId = parsePositiveInt(sandboxWorkflowId.value)
    if (!targetWorkflowId) return
    let targetNodeId = parsePositiveInt(preferredNodeIds[0])
    if (!targetNodeId) {
      const graphNodes = Array.isArray(decomposeNodes.value) ? decomposeNodes.value : []
      const emp = graphNodes.find((n) => n && n.node_type === 'employee')
      targetNodeId = parsePositiveInt(emp?.id)
    }
    if (!targetNodeId) return
    if (!currentWorkflow.value || parsePositiveInt(currentWorkflow.value.id) !== targetWorkflowId) {
      await editWorkflow(targetWorkflowId)
    } else {
      activeTab.value = 'editor'
    }
    await nextTick()
    focusedNodeId.value = targetNodeId
    const el = document.getElementById(`workflow-node-${targetNodeId}`)
    if (el && typeof el.scrollIntoView === 'function') {
      try {
        el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'center' })
      } catch {
        /* ignore */
      }
    }
    setTimeout(() => {
      if (focusedNodeId.value === targetNodeId) focusedNodeId.value = 0
    }, 3200)
  }

  watch(sandboxEmployeeId, async (id) => {
    if (activeTab.value !== 'sandbox') return
    sandboxReport.value = null
    sandboxError.value = ''
    if (!id) {
      sandboxWorkflowCandidates.value = []
      sandboxWorkflowId.value = 0
      decomposeNodes.value = []
      decomposeEdges.value = []
      return
    }
    await rebuildSandboxWorkflowCandidates()
  })

  watch(sandboxWorkflowId, async (id) => {
    if (activeTab.value !== 'sandbox') return
    if (id) await loadDecomposeGraph(id)
  })

  /** 仅重置本域内存态（原 resetAutomationWorkbenchLocalState 中的沙盒部分） */
  function reset() {
    sandboxEmployeeId.value = ''
    sandboxWorkflowCandidates.value = []
    sandboxMappingLoading.value = false
    sandboxMappingError.value = ''
    sandboxMappingNodeHits.value = 0
    sandboxMappingManifestHits.value = 0
    sandboxWorkflowId.value = 0
    sandboxLoading.value = false
    sandboxAutoCreateBusy.value = false
    sandboxReport.value = null
    sandboxError.value = ''
    lastRunMeta.value = { mode: '', startedAt: '', precheck: null }
    decomposeNodes.value = []
    decomposeEdges.value = []
    decomposeLoading.value = false

    sandboxPresetId.value = 'topic'
    applySandboxPreset('topic')

    workflowDetailCache.clear()
  }

  return {
    sandboxEmployeeId,
    sandboxWorkflowCandidates,
    sandboxMappingLoading,
    sandboxMappingError,
    sandboxMappingNodeHits,
    sandboxMappingManifestHits,
    sandboxWorkflowId,
    sandboxInputJson,
    sandboxLoading,
    sandboxAutoCreateBusy,
    sandboxReport,
    sandboxError,
    lastRunMeta,
    decomposeNodes,
    decomposeEdges,
    decomposeLoading,
    sandboxPresetId,
    workflowDetailCache,
    realRunDisabledReason,
    canRunReal,
    realPrecheckSummary,
    getWorkflowDetailCached,
    rebuildSandboxWorkflowCandidates,
    createSandboxWorkflowForEmployee,
    loadDecomposeGraph,
    // 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定
    parseSandboxInput,
    applySandboxPreset,
    onSandboxPresetChange,
    openSandboxFor,
    runSandboxValidate,
    runSandboxMock,
    runSandboxReal,
    reset,
  }
}
