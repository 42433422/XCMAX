import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { computeGraphSummary, buildMermaidFlowchart } from '../workflowMermaid'
import { errMessage } from '../utils/errMessage'
import type { ExecutionRow, WorkflowRow } from '../views/workflow/workflowTypes'
import { useWorkflowEmployees } from './useWorkflowEmployees'
import { useWorkflowEditor } from './useWorkflowEditor'
import { useWorkflowSandbox } from './useWorkflowSandbox'
import { useWorkflowTriggers } from './useWorkflowTriggers'
import { useWorkflowHomeDraft } from './useWorkflowHomeDraft'

/**
 * WorkflowView 页面编排器：聚合员工 / 编辑器 / 沙盒 / 触发器 / 首页草稿各域，
 * 并保留跨域的列表 CRUD、一键清理、路由同步与生命周期逻辑（均自 WorkflowView.vue 原样迁移）。
 */
export function useWorkflowPage() {
  const route = useRoute()
  const router = useRouter()

  // 状态管理
  const activeTab = ref('list')
  const loading = ref(false)
  const bulkDeleteInactiveBusy = ref(false)
  /** 一键清理：删除全部任务进行中 */
  const purgeAutomationBusy = ref(false)
  const message = ref('')
  const messageOk = ref(true)
  const workflows = ref<WorkflowRow[]>([])
  const executions = ref<ExecutionRow[]>([])

  // 弹窗状态
  const showCreateModal = ref(false)

  // 新工作流表单
  const newWorkflow = ref({
    name: '',
    description: '',
  })

  // 消息提示
  function flash(msg: string, ok = true) {
    message.value = msg
    messageOk.value = ok
    setTimeout(() => { message.value = '' }, 5000)
  }

  const employeesApi = useWorkflowEmployees({ flash })
  const { employees, loadEmployees } = employeesApi

  // 加载工作流列表
  async function loadWorkflows() {
    loading.value = true
    try {
      const res = await api.listWorkflows()
      workflows.value = Array.isArray(res) ? (res as WorkflowRow[]) : []
    } catch (e) {
      flash('加载工作流失败: ' + ((e as Error)?.message || String(e)), false)
      workflows.value = []
    } finally {
      loading.value = false
    }
  }

  // 日期格式化
  function formatDate(iso: string | undefined) {
    if (!iso) return ''
    return new Date(iso).toLocaleString('zh-CN')
  }

  // 获取状态标签
  function getStatusLabel(status: string | undefined) {
    const labels: Record<string, string> = {
      pending: '待执行',
      running: '执行中',
      completed: '已完成',
      failed: '失败'
    }
    return (status && labels[status]) || status || '未知'
  }

  // 获取工作流名称
  function getWorkflowName(workflowId: number | undefined) {
    if (workflowId == null || !Number.isFinite(Number(workflowId))) return '未知工作流'
    const workflow = workflows.value.find((w) => w.id === workflowId)
    return workflow ? workflow.name : '未知工作流'
  }

  // 加载执行记录（聚合所有工作流）
  async function loadExecutions() {
    loading.value = true
    try {
      if (!workflows.value.length) {
        await loadWorkflows()
      }
      const parts = []
      for (const w of workflows.value) {
        try {
          const rows = await api.listWorkflowExecutions(w.id)
          for (const r of rows || []) {
            parts.push({ ...r, workflow_id: w.id })
          }
        } catch {
          /* 单个失败跳过 */
        }
      }
      parts.sort((a, b) => new Date(b.started_at || 0).getTime() - new Date(a.started_at || 0).getTime())
      executions.value = parts
    } catch (e) {
      flash('加载执行记录失败: ' + errMessage(e), false)
      executions.value = []
    } finally {
      loading.value = false
    }
  }

  const homeDraft = useWorkflowHomeDraft({ route, flash, newWorkflow, showCreateModal })
  const { homeLlmHint, homeIntentHint } = homeDraft

  // 编辑器域先创建；其 editWorkflow 依赖的 loadDecomposeGraph 由沙盒域创建后回填
  let loadDecomposeGraphLate: (workflowId: number) => Promise<void> = async () => {}
  const editorApi = useWorkflowEditor({
    loading,
    activeTab,
    flash,
    loadDecomposeGraph: (workflowId: number) => loadDecomposeGraphLate(workflowId),
  })
  const sandboxApi = useWorkflowSandbox({
    flash,
    employees,
    workflows,
    activeTab,
    currentWorkflow: editorApi.currentWorkflow,
    focusedNodeId: editorApi.focusedNodeId,
    editWorkflow: editorApi.editWorkflow,
    loadWorkflows,
    pickEmployeeNameById: employeesApi.pickEmployeeNameById,
  })
  loadDecomposeGraphLate = sandboxApi.loadDecomposeGraph
  const triggersApi = useWorkflowTriggers({ workflows, loadWorkflows })

  const { currentWorkflow, nodes, edges, canvas } = editorApi
  const {
    sandboxWorkflowId,
    sandboxEmployeeId,
    sandboxReport,
    sandboxError,
    decomposeNodes,
    decomposeEdges,
    loadDecomposeGraph,
    rebuildSandboxWorkflowCandidates,
    workflowDetailCache,
  } = sandboxApi

  const graphForDecompose = computed(() => {
    if (activeTab.value === 'editor' && currentWorkflow.value) {
      return { nodes: nodes.value, edges: edges.value }
    }
    if (activeTab.value === 'sandbox' && sandboxWorkflowId.value) {
      return { nodes: decomposeNodes.value, edges: decomposeEdges.value }
    }
    return { nodes: [], edges: [] }
  })

  const graphSummary = computed(() =>
    computeGraphSummary(graphForDecompose.value.nodes, graphForDecompose.value.edges),
  )

  const mermaidSource = computed(() =>
    buildMermaidFlowchart(graphForDecompose.value.nodes, graphForDecompose.value.edges),
  )

  async function copyMermaidToClipboard() {
    const t = mermaidSource.value
    try {
      await navigator.clipboard.writeText(t)
      flash('已复制 Mermaid 到剪贴板', true)
    } catch {
      flash('复制失败，请手动全选复制', false)
    }
  }

  /** 仅重置本页 UI / 沙盒 / 触发器 / 画布内存态，不请求删除工作流 */
  function resetAutomationWorkbenchLocalState() {
    message.value = ''
    sandboxApi.reset()
    triggersApi.reset()
    editorApi.reset()
    homeLlmHint.value = ''
    homeIntentHint.value = ''
    newWorkflow.value = { name: '', description: '' }
    showCreateModal.value = false
    activeTab.value = 'list'
    executions.value = []
  }

  /** 一键清理：删光账号下全部自动化任务 + 重置本页本地状态（与「workflow-page 全删」语义一致） */
  async function purgeAutomationWorkbenchFull() {
    if (purgeAutomationBusy.value) return

    const list = Array.isArray(workflows.value) ? workflows.value : []
    const ids = list.map((w) => (w && w.id != null ? Number(w.id) : 0)).filter((n) => Number.isFinite(n) && n > 0)

    if (!ids.length) {
      if (
        !window.confirm(
          '当前没有任何已保存的自动化任务。将仅清空：本页提示、沙盒与触发器表单、运行记录列表缓存、以及未提交的创建弹窗等本地状态。是否继续？',
        )
      ) {
        return
      }
      resetAutomationWorkbenchLocalState()
      flash('已清理本页本地状态', true)
      await loadWorkflows()
      if (activeTab.value === 'executions') await loadExecutions()
      return
    }

    if (!localStorage.getItem('modstore_token')) {
      flash('请先登录后再使用一键清理（将删除全部自动化任务）', false)
      return
    }

    const activeCount = list.filter((w) => w && w.is_active).length
    const activeHint =
      activeCount > 0 ? `\n\n其中有 ${activeCount} 个为「激活」状态，将一并永久删除。` : ''

    if (
      !window.confirm(
        `确定删除当前账号下全部 ${ids.length} 个自动化任务？\n含节点、边、运行记录、触发器与版本快照等，不可恢复。${activeHint}\n\n同时将清空本页沙盒、触发器表单与画布状态。是否继续？`,
      )
    ) {
      return
    }

    purgeAutomationBusy.value = true
    resetAutomationWorkbenchLocalState()
    const failed: Array<{ id: number; err: string }> = []
    try {
      for (const id of ids) {
        try {
          await api.deleteWorkflow(id)
        } catch (e) {
          failed.push({ id, err: (e as Error)?.message || String(e) })
        }
      }
      if (failed.length) {
        flash(
          `已删除 ${ids.length - failed.length} 个，失败 ${failed.length} 个：${failed.map((f) => f.id).join(', ')}`,
          false,
        )
      } else {
        flash(`已清空自动化任务（共删除 ${ids.length} 个）`, true)
      }
    } finally {
      purgeAutomationBusy.value = false
      workflowDetailCache.clear()
      await loadWorkflows()
      if (activeTab.value === 'executions') await loadExecutions()
      if (activeTab.value === 'triggers') await triggersApi.loadTriggersPanel()
    }
  }

  /** 批量删除列表中所有未激活（is_active === false）的工作流 */
  async function bulkDeleteInactiveWorkflows() {
    const targets = (workflows.value || []).filter((w) => w && !w.is_active)
    if (!targets.length) {
      flash('当前没有「未激活」的自动化任务可删', false)
      return
    }
    if (
      !window.confirm(
        `将永久删除 ${targets.length} 个未激活任务（含节点、边、运行记录、触发器与版本快照）。不可恢复。\n\n任务名预览：${targets
          .slice(0, 5)
          .map((w) => w.name || `#${w.id}`)
          .join('、')}${targets.length > 5 ? '…' : ''}\n\n确定继续？`,
      )
    ) {
      return
    }
    bulkDeleteInactiveBusy.value = true
    let okCount = 0
    try {
      for (const w of targets) {
        await api.deleteWorkflow(w.id)
        okCount += 1
      }
      flash(`已删除 ${okCount} 个未激活任务`, true)
      await loadWorkflows()
      if (activeTab.value === 'executions') {
        await loadExecutions()
      }
      if (activeTab.value === 'triggers' && triggersApi.triggersWorkflowId.value) {
        await triggersApi.onTriggersWorkflowChange()
      }
    } catch (e: unknown) {
      flash(`批量删除中断（已删 ${okCount} 个）：${errMessage(e)}`, false)
      await loadWorkflows()
    } finally {
      bulkDeleteInactiveBusy.value = false
    }
  }

  // 创建工作流
  async function createWorkflow() {
    if (!newWorkflow.value.name) {
      flash('请输入工作流名称', false)
      return
    }

    try {
      const _res = await api.createWorkflow(newWorkflow.value.name, newWorkflow.value.description)
      flash('工作流创建成功')
      showCreateModal.value = false
      newWorkflow.value = { name: '', description: '' }
      homeLlmHint.value = ''
      homeIntentHint.value = ''
      await loadWorkflows()
    } catch (e: unknown) {
      flash('创建工作流失败: ' + errMessage(e), false)
    }
  }

  // 执行工作流（生产路径，写入执行记录）
  async function executeWorkflow(workflowId: number) {
    try {
      await api.executeWorkflow(workflowId, {})
      flash('工作流执行成功')
      activeTab.value = 'executions'
      await loadExecutions()
    } catch (e: unknown) {
      flash('执行工作流失败: ' + errMessage(e), false)
    }
  }

  // 切换工作流状态
  async function toggleWorkflowStatus(workflowId: number, isActive: boolean) {
    try {
      await api.updateWorkflow(workflowId, null, null, isActive)
      flash(`工作流已${isActive ? '激活' : '停用'}`)
      await loadWorkflows()
    } catch (e: unknown) {
      flash('更新工作流状态失败: ' + errMessage(e), false)
    }
  }

  // 删除工作流
  async function deleteWorkflow(workflowId: number) {
    if (!confirm('确定要删除这个工作流吗？')) {
      return
    }

    try {
      await api.deleteWorkflow(workflowId)
      flash('工作流删除成功')
      await loadWorkflows()
    } catch (e: unknown) {
      flash('删除工作流失败: ' + errMessage(e), false)
    }
  }

  // 编辑工作流（跳转可视化编辑器）
  function openV2Editor(workflowId: number) {
    router.push({ name: 'workflow-v2-editor', params: { id: String(workflowId) } })
  }

  /** ?edit=id&tab=sandbox|editor|list|executions — 进入后清除 query，避免刷新重复进入 */
  async function applyWorkflowRouteQuery() {
    const rawEdit = route.query.edit
    const tabRaw = String(route.query.tab || '')
      .toLowerCase()
      .trim()
    const allowed = new Set(['list', 'editor', 'sandbox', 'executions'])
    const tab = allowed.has(tabRaw) ? tabRaw : ''

    if (rawEdit != null && String(rawEdit).trim() !== '') {
      const id = parseInt(String(rawEdit), 10)
      if (!Number.isNaN(id) && id > 0) {
        showCreateModal.value = false
        await loadWorkflows()
        if (tab === 'sandbox') {
          sandboxWorkflowId.value = id
          sandboxReport.value = null
          sandboxError.value = ''
          activeTab.value = 'sandbox'
          await loadDecomposeGraph(id)
        } else if (tab === 'executions') {
          activeTab.value = 'executions'
          await loadExecutions()
        } else if (tab === 'list') {
          activeTab.value = 'list'
          currentWorkflow.value = null
          decomposeNodes.value = []
          decomposeEdges.value = []
        } else {
          await editorApi.editWorkflow(id)
        }
        try {
          await router.replace({ name: 'workbench-workflow', query: {} })
        } catch {
          /* ignore */
        }
        return
      }
    }

    if (tab && allowed.has(tab)) {
      activeTab.value = tab
      try {
        await router.replace({ name: 'workbench-workflow', query: {} })
      } catch {
        /* ignore */
      }
    }
  }

  // 初始化事件监听器
  onMounted(async () => {
    await Promise.all([loadWorkflows(), loadEmployees()])

    homeDraft.restoreHomeDraft()

    await applyWorkflowRouteQuery()

    // 添加全局鼠标事件监听器
    document.addEventListener('mousemove', editorApi.onMouseMove)
    document.addEventListener('mouseup', editorApi.onMouseUp)

    // 添加画布点击事件监听器
    if (canvas.value) {
      canvas.value.addEventListener('click', editorApi.onCanvasClick)
    }
  })

  onUnmounted(() => {
    document.removeEventListener('mousemove', editorApi.onMouseMove)
    document.removeEventListener('mouseup', editorApi.onMouseUp)
    if (canvas.value) {
      canvas.value.removeEventListener('click', editorApi.onCanvasClick)
    }
  })

  watch(activeTab, async (newTab) => {
    if (newTab === 'executions') {
      await loadExecutions()
    }
    if (newTab === 'triggers') {
      await triggersApi.loadTriggersPanel()
    }
    if (newTab === 'sandbox') {
      if (!workflows.value.length) {
        await loadWorkflows()
      }
      if (!employees.value.length) {
        await loadEmployees()
      }
      if (!sandboxEmployeeId.value && employees.value.length) {
        sandboxEmployeeId.value = String(employees.value[0].id || '')
        return
      }
      if (sandboxEmployeeId.value) {
        await rebuildSandboxWorkflowCandidates()
      } else if (sandboxWorkflowId.value) {
        await loadDecomposeGraph(sandboxWorkflowId.value)
      }
    }
  })

  watch(
    () => route.fullPath,
    async () => {
      if (route.name !== 'workbench-workflow') return
      if (route.query.edit == null && String(route.query.tab || '').trim() === '') return
      await applyWorkflowRouteQuery()
    },
  )

  return {
    // 基础状态
    activeTab,
    loading,
    bulkDeleteInactiveBusy,
    purgeAutomationBusy,
    message,
    messageOk,
    workflows,
    executions,
    showCreateModal,
    newWorkflow,
    // 基础函数
    flash,
    formatDate,
    getStatusLabel,
    getWorkflowName,
    loadWorkflows,
    loadExecutions,
    // 列表 CRUD / 执行
    executeWorkflow,
    createWorkflow,
    openV2Editor,
    toggleWorkflowStatus,
    deleteWorkflow,
    bulkDeleteInactiveWorkflows,
    purgeAutomationWorkbenchFull,
    // 测试兼容面：既有测试经 setupState 访问原单文件顶层绑定
    applyWorkflowRouteQuery,
    resetAutomationWorkbenchLocalState,
    // 图摘要
    graphSummary,
    mermaidSource,
    copyMermaidToClipboard,
    // 各域
    ...employeesApi,
    ...editorApi,
    ...sandboxApi,
    ...triggersApi,
    ...homeDraft,
  }
}
