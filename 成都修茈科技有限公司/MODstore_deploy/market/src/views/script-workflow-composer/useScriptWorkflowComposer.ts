/**
 * 脚本工作流编排视图逻辑（由 ScriptWorkflowComposerView.vue 原单文件机械迁出，行为不变）。
 * 覆盖：Brief 表单、模板、文件上传、Agent SSE 循环、反馈/保存/沙箱/启用。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../../api'
import { getAccessToken } from '../../infrastructure/storage/tokenStore'
import { formatPlanMdForDisplay } from '../../utils/planMdDisplay'

export type Stage = 'brief' | 'loop' | 'sandbox'

export interface BriefInput {
  filename: string
  description: string
}

export interface AgentEvent {
  type: string
  iteration: number
  payload: AgentPayload
}

export interface AgentOutcome {
  ok?: boolean
  final_code?: string
  [key: string]: unknown
}

export interface SandboxOutput {
  filename: string
  size?: number
  [key: string]: unknown
}

export interface AgentPayload {
  plan_md?: unknown
  code?: string
  ok?: boolean
  errors?: unknown[]
  outputs?: SandboxOutput[]
  stdout_tail?: string
  stderr_tail?: string
  reason?: unknown
  session_id?: string
  outcome?: AgentOutcome
  [key: string]: unknown
}

export interface SandboxRun {
  id: number | string
  status?: string
  stdout_tail?: string
  stderr_tail?: string
  outputs?: SandboxOutput[]
}

export interface BriefState {
  goal: string
  outputs: string
  acceptance: string
  fallback: string
  trigger_type: string
  inputs: BriefInput[]
  references: Record<string, unknown>
}

export interface ScriptWorkflowResponse {
  id: number
  name: string
  brief?: Partial<BriefState>
  script_text?: string
}

export function useScriptWorkflowComposer() {
  const route = useRoute()
  const router = useRouter()

  const stage = ref<Stage>('brief')
  const stageRank = computed<number>(() => {
    if (committed.value) return 3
    if (stage.value === 'sandbox') return 3
    if (stage.value === 'loop') return 2
    return 1
  })

  const brief = reactive({
    goal: '',
    outputs: '',
    acceptance: '',
    fallback: '',
    trigger_type: 'manual',
    inputs: [] as BriefInput[],
    references: {} as Record<string, unknown>,
  })
  const uploadedFiles = ref<File[]>([])
  const events = ref<AgentEvent[]>([])
  const sessionId = ref<string>('')
  const outcome = ref<AgentOutcome | null>(null)
  const loopRunning = ref(false)
  const busy = ref(false)
  const tab = ref<'code' | 'output' | 'sandbox'>('code')
  const committed = ref(false)
  const workflowId = ref<number | null>(null)
  const workflowName = ref<string>('')
  const feedback = ref<string>('')
  const sandboxFiles = ref<File[]>([])
  const sandboxBusy = ref(false)
  const lastSandboxRun = ref<SandboxRun | null>(null)
  const canActivate = computed(() => lastSandboxRun.value?.status === 'success')

  const headTitle = computed(() => {
    if (route.params.id) return '改进脚本工作流'
    return '新建脚本工作流'
  })

  const briefHints = computed(() => ({
    goal: brief.goal.trim().length < 20 ? '建议补充：业务背景 + 目标，越具体越好' : '',
    inputs:
      uploadedFiles.value.length === 0
        ? '强烈建议至少上传一个真实样本文件；空跑成功率会显著下降'
        : brief.inputs.some((i) => !i.description.trim())
          ? '每个文件最好用一句话说明含义（字段名、单位等）'
          : '',
    outputs: brief.outputs.trim().length < 20 ? '建议补充：输出文件名 + 字段 + 至少 1 个示例值' : '',
    acceptance:
      brief.acceptance.trim().length < 20
        ? '建议补充可机器判定的条件，例如「outputs/x.json 存在且 amount > 0」'
        : '',
  }))

  const templates = [
    {
      key: 'sales_summary',
      title: '多份 Excel 汇总',
      desc: '把上传的若干 .xlsx 合并成一张总览，分组、排序、出文件',
    },
    {
      key: 'contract_extract',
      title: '合同信息提取',
      desc: '用 ai() 从文本中抽取金额/日期/对手方，写 JSON',
    },
    {
      key: 'data_clean',
      title: '数据清洗',
      desc: '处理空值、统一日期格式、去重；输出干净 csv',
    },
    {
      key: 'feishu_post',
      title: '飞书播报',
      desc: '把 csv 概览发到飞书群（http_get + ai 总结）',
    },
  ]

  function applyTemplate(key: string) {
    switch (key) {
      case 'sales_summary':
        brief.goal = '把 inputs/ 下的多个销售明细 .xlsx 合并成一张总览。每个文件的列基本相同：日期、SKU、数量、金额。'
        brief.outputs = 'outputs/总览.xlsx，含 sheet "明细"（合并后所有行）与 sheet "总览"（按 SKU 聚合，列：SKU/总销量/总销售额）。'
        brief.acceptance = 'outputs/总览.xlsx 存在；明细 sheet 行数 = 各输入文件行数之和；总览 sheet 销售额合计 = 明细销售额合计。'
        break
      case 'contract_extract':
        brief.goal = '从 inputs/ 下的合同文本（txt/docx）里抽取核心字段。'
        brief.outputs = 'outputs/contracts.json，列表，每项 {file, party_a, party_b, amount, start, end}。'
        brief.acceptance = 'outputs/contracts.json 存在；条数 = 输入文件数；amount 都是 number。'
        brief.fallback = '当原文金额表述不规范时，用 modstore_runtime.ai(prompt, schema={amount:"number"}) 兜底。'
        break
      case 'data_clean':
        brief.goal = '清洗 inputs/ 下的 csv：去重、统一日期格式 (YYYY-MM-DD)、空值用上一条非空填补。'
        brief.outputs = 'outputs/clean.csv，列 = 输入列。'
        brief.acceptance = 'outputs/clean.csv 存在；无重复行；日期列均符合 YYYY-MM-DD。'
        break
      case 'feishu_post':
        brief.goal = '从 inputs/ 中的 csv 取 KPI 数据，让 AI 总结一段话，调飞书 webhook 发送。'
        brief.outputs = 'outputs/post.json，记录响应 status 与摘要。'
        brief.acceptance = 'outputs/post.json 存在；http_status == 200；summary 非空。'
        brief.fallback = '飞书 webhook 域名要先在管理员处加入 allowlist，否则 SDK 会报错。'
        break
    }
  }

  function onFilesPicked(e: Event) {
    const files = Array.from((e.target as HTMLInputElement).files || [])
    uploadedFiles.value.push(...files)
    files.forEach((f) => brief.inputs.push({ filename: f.name, description: '' }))
  }

  function removeFile(idx: number) {
    uploadedFiles.value.splice(idx, 1)
    brief.inputs.splice(idx, 1)
  }

  function onSandboxFilesPicked(e: Event) {
    sandboxFiles.value.push(...Array.from((e.target as HTMLInputElement).files || []))
  }

  function planMdHasMermaid(md: unknown): boolean {
    return /```mermaid/i.test(String(md || ''))
  }

  function mermaidExcerpt(md: unknown): string {
    const m = String(md || '').match(/```mermaid\s*([\s\S]*?)```/i)
    return m ? m[1].trim().slice(0, 2400) : ''
  }

  function humanSize(n: number): string {
    if (n < 1024) return `${n}B`
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}K`
    return `${(n / 1024 / 1024).toFixed(2)}M`
  }

  function trimCode(c?: string) {
    if (!c) return ''
    return c.length > 3000 ? c.slice(0, 3000) + '\n…' : c
  }

  function tail(s: string | undefined, n: number): string {
    if (!s) return ''
    return s.length <= n ? s : s.slice(-n)
  }

  function eventLabel(ev: AgentEvent): string {
    const map: Record<string, string> = {
      session_started: 'AI 会话开始',
      context: '收集上下文',
      plan: '生成计划',
      code: `第 ${ev.iteration + 1} 轮：写代码`,
      check: `第 ${ev.iteration + 1} 轮：静态检查`,
      run: `第 ${ev.iteration + 1} 轮：沙箱执行`,
      observe: `第 ${ev.iteration + 1} 轮：AI 验收`,
      repair: `第 ${ev.iteration + 1} 轮：修复重写`,
      done: '完成',
      error: '失败',
    }
    return map[ev.type] || ev.type
  }

  const currentCode = computed(() => {
    for (let i = events.value.length - 1; i >= 0; i--) {
      const ev = events.value[i]
      if (ev.type === 'code' || ev.type === 'repair' || ev.type === 'done') {
        return ev.payload?.code || ev.payload?.outcome?.final_code || ''
      }
    }
    return ''
  })

  const lastRun = computed(() => {
    for (let i = events.value.length - 1; i >= 0; i--) {
      if (events.value[i].type === 'run') return events.value[i]
    }
    return null
  })
  const runStdout = computed(() => lastRun.value?.payload?.stdout_tail || '')
  const runStderr = computed(() => lastRun.value?.payload?.stderr_tail || '')
  const runOutputs = computed(() => lastRun.value?.payload?.outputs || [])

  async function consumeSseStream(path: string, init: RequestInit = {}) {
    const headers = new Headers(init.headers || {})
    const token = getAccessToken()
    if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
    const res = await fetch(path, { ...init, headers })
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => '')
      throw new Error(`SSE 启动失败: HTTP ${res.status} ${text}`)
    }
    const reader = res.body.getReader()
    const dec = new TextDecoder('utf-8')
    let buf = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let nl = buf.indexOf('\n\n')
      while (nl !== -1) {
        const frame = buf.slice(0, nl)
        buf = buf.slice(nl + 2)
        const line = frame.split('\n').find((l) => l.startsWith('data:'))
        if (line) {
          try {
            const ev = JSON.parse(line.slice(5).trim())
            handleEvent(ev)
          } catch (err) {
            console.warn('failed to parse SSE frame', err, frame)
          }
        }
        nl = buf.indexOf('\n\n')
      }
    }
  }

  function handleEvent(ev: AgentEvent) {
    if (ev.type === 'session_started') {
      sessionId.value = ev.payload?.session_id || ''
      return
    }
    events.value.push(ev)
    if (ev.type === 'done' || ev.type === 'error') {
      loopRunning.value = false
      outcome.value = ev.payload?.outcome || null
    } else if (ev.type === 'run') {
      tab.value = 'output'
    }
  }

  async function startAgentLoop() {
    if (busy.value) return
    busy.value = true
    events.value = []
    outcome.value = null
    loopRunning.value = true
    stage.value = 'loop'
    tab.value = 'code'
    try {
      const fd = new FormData()
      fd.set('brief_json', JSON.stringify(brief))
      uploadedFiles.value.forEach((f) => fd.append('files', f))
      await consumeSseStream('/api/script-workflows/sessions', { method: 'POST', body: fd })
    } catch (e: unknown) {
      events.value.push({ type: 'error', iteration: -1, payload: { reason: e instanceof Error ? e.message : String(e) } })
      loopRunning.value = false
    } finally {
      busy.value = false
    }
  }

  async function startEditWithAi(hint: string) {
    if (!workflowId.value) return
    loopRunning.value = true
    outcome.value = null
    stage.value = 'loop'
    tab.value = 'code'
    try {
      await consumeSseStream(`/api/script-workflows/${workflowId.value}/edit-with-ai`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hint }),
      })
    } catch (e: unknown) {
      events.value.push({ type: 'error', iteration: -1, payload: { reason: e instanceof Error ? e.message : String(e) } })
      loopRunning.value = false
    }
  }

  async function submitFeedback() {
    if (!feedback.value.trim()) return
    const hint = feedback.value.trim()
    feedback.value = ''
    // 编辑已有工作流时尚无活跃 session，调用 edit-with-ai 创建新 agent loop
    if (!sessionId.value && workflowId.value) {
      await startEditWithAi(hint)
      return
    }
    if (!sessionId.value) return
    loopRunning.value = true
    outcome.value = null
    try {
      await consumeSseStream(`/api/script-workflows/sessions/${encodeURIComponent(sessionId.value)}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hint }),
      })
    } catch (e: unknown) {
      events.value.push({ type: 'error', iteration: -1, payload: { reason: e instanceof Error ? e.message : String(e) } })
      loopRunning.value = false
    }
  }

  async function commitToWorkflow() {
    if (!sessionId.value || !workflowName.value.trim()) return
    try {
      const wf = (await api.commitScriptWorkflowSession(sessionId.value, {
        name: workflowName.value.trim(),
        schema_in: {},
      })) as ScriptWorkflowResponse
      committed.value = true
      workflowId.value = wf.id
      stage.value = 'sandbox'
      tab.value = 'sandbox'
    } catch (e: unknown) {
      alert('保存失败：' + (e instanceof Error ? e.message : String(e)))
    }
  }

  async function runManualSandbox() {
    if (!workflowId.value) return
    sandboxBusy.value = true
    try {
      const r = (await api.sandboxRunScriptWorkflow(workflowId.value, sandboxFiles.value)) as SandboxRun
      lastSandboxRun.value = r
    } catch (e: unknown) {
      alert('沙箱执行失败：' + (e instanceof Error ? e.message : String(e)))
    } finally {
      sandboxBusy.value = false
    }
  }

  async function downloadSandboxOutput(output: SandboxOutput) {
    if (!workflowId.value || !lastSandboxRun.value?.id || !output?.filename) return
    try {
      const blob = await api.downloadScriptWorkflowRunFile(
        workflowId.value,
        lastSandboxRun.value.id,
        String(output.filename),
      )
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = String(output.filename)
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 4000)
    } catch (e: unknown) {
      alert('下载失败：' + (e instanceof Error ? e.message : String(e)))
    }
  }

  async function activate() {
    if (!workflowId.value) return
    try {
      await api.activateScriptWorkflow(workflowId.value)
      router.push({ name: 'workbench-script-workflow-detail', params: { id: workflowId.value } })
    } catch (e: unknown) {
      alert('启用失败：' + (e instanceof Error ? e.message : String(e)))
    }
  }

  function goList() {
    router.push({ name: 'workbench-script-workflows' })
  }

  onMounted(async () => {
    // edit-with-ai 模式：从已有工作流加载 brief 直接进 loop
    const id = route.params.id
    if (id && typeof id === 'string') {
      try {
        const wf = (await api.getScriptWorkflow(id)) as ScriptWorkflowResponse
        Object.assign(brief, wf.brief || {})
        workflowId.value = wf.id
        workflowName.value = wf.name
        committed.value = true
        stage.value = 'sandbox'
        tab.value = 'sandbox'
        const runRows = (await api.listScriptWorkflowRuns(wf.id).catch(() => [])) as SandboxRun[]
        lastSandboxRun.value = Array.isArray(runRows) && runRows.length ? runRows[0] : null
        events.value = [
          { type: 'context', iteration: 0, payload: { existing: true } },
          { type: 'done', iteration: 0, payload: { code: wf.script_text, outcome: { ok: true, final_code: wf.script_text } } },
        ]
        outcome.value = { ok: true, final_code: wf.script_text }
      } catch (e: unknown) {
        alert('加载工作流失败：' + (e instanceof Error ? e.message : String(e)))
      }
    }
  })

  return {
    formatPlanMdForDisplay,
    stage,
    stageRank,
    brief,
    uploadedFiles,
    events,
    sessionId,
    outcome,
    loopRunning,
    busy,
    tab,
    committed,
    workflowId,
    workflowName,
    feedback,
    sandboxFiles,
    sandboxBusy,
    lastSandboxRun,
    canActivate,
    headTitle,
    briefHints,
    templates,
    applyTemplate,
    onFilesPicked,
    removeFile,
    onSandboxFilesPicked,
    planMdHasMermaid,
    mermaidExcerpt,
    humanSize,
    trimCode,
    tail,
    eventLabel,
    currentCode,
    lastRun,
    runStdout,
    runStderr,
    runOutputs,
    handleEvent,
    startAgentLoop,
    startEditWithAi,
    submitFeedback,
    commitToWorkflow,
    runManualSandbox,
    downloadSandboxOutput,
    activate,
    goList,
  }
}
