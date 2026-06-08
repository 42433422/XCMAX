<template>
  <div class="swc">
    <header class="swc-head">
      <button class="swc-back" type="button" @click="goList">← 返回列表</button>
      <h1>{{ headTitle }}</h1>
      <ol class="swc-steps" :data-stage="stage">
        <li :class="{ done: stageRank >= 1, active: stage === 'brief' }">1 描述需求</li>
        <li :class="{ done: stageRank >= 2, active: stage === 'loop' }">2 AI 编码</li>
        <li :class="{ done: stageRank >= 3, active: stage === 'sandbox' }">3 沙箱试用</li>
        <li :class="{ done: stageRank >= 4 }">4 启用</li>
      </ol>
    </header>

    <!-- ===================== Brief 阶段 ===================== -->
    <section v-if="stage === 'brief'" class="swc-brief">
      <p class="swc-brief-tip">
        填写越详细，一次成功率越高。所有字段都会作为 AI 生成时的上下文，建议复述具体业务术语、字段名、阈值等。
      </p>

      <details class="swc-templates">
        <summary>从模板开始（可选）</summary>
        <div class="swc-templates-list">
          <button
            v-for="t in templates"
            :key="t.key"
            type="button"
            class="swc-template"
            @click="applyTemplate(t.key)"
          >
            <strong>{{ t.title }}</strong>
            <span>{{ t.desc }}</span>
          </button>
        </div>
      </details>

      <div class="swc-field">
        <label>任务目标 <span class="req">*</span></label>
        <textarea
          v-model="brief.goal"
          rows="3"
          placeholder="例：每天把多个销售明细 .xlsx 汇总成一张当日总览表，按门店分 sheet，按 SKU 排序"
        />
        <p v-if="briefHints.goal" class="swc-hint">{{ briefHints.goal }}</p>
      </div>

      <div class="swc-field">
        <label>输入数据 <span class="req">*</span></label>
        <input type="file" multiple @change="onFilesPicked" />
        <ul v-if="uploadedFiles.length" class="swc-file-list">
          <li v-for="(f, idx) in uploadedFiles" :key="idx">
            <span class="swc-file-name">{{ f.name }}</span>
            <span class="swc-file-size">{{ humanSize(f.size) }}</span>
            <input
              v-model="brief.inputs[idx].description"
              type="text"
              class="swc-file-desc"
              placeholder="文件含义（如：销售明细，列：日期/SKU/数量/金额）"
            />
            <button type="button" class="swc-file-x" @click="removeFile(idx)">×</button>
          </li>
        </ul>
        <p v-if="briefHints.inputs" class="swc-hint">{{ briefHints.inputs }}</p>
      </div>

      <div class="swc-field">
        <label>输出要求 <span class="req">*</span></label>
        <textarea
          v-model="brief.outputs"
          rows="3"
          placeholder="例：outputs/总览.xlsx，每行字段：门店 / SKU / 销量 / 销售额，按销售额倒序"
        />
        <p v-if="briefHints.outputs" class="swc-hint">{{ briefHints.outputs }}</p>
      </div>

      <div class="swc-field">
        <label>成功判定标准 <span class="req">*</span></label>
        <textarea
          v-model="brief.acceptance"
          rows="3"
          placeholder="例：outputs/总览.xlsx 存在；行数 = 输入文件 SKU 去重数；销售额合计与输入合计相等"
        />
        <p class="swc-hint">这条会作为 AI 验收官的依据，越具体越好。</p>
        <p v-if="briefHints.acceptance" class="swc-hint">{{ briefHints.acceptance }}</p>
      </div>

      <div class="swc-field">
        <label>失败兜底（可选）</label>
        <textarea
          v-model="brief.fallback"
          rows="2"
          placeholder="例：遇到金额为空的行用 ai('该行金额疑似缺失，请基于上下文推断') 兜底"
        />
      </div>

      <div class="swc-field swc-row">
        <label>触发方式</label>
        <select v-model="brief.trigger_type">
          <option value="manual">手动</option>
          <option value="cron">定时 (cron)</option>
          <option value="webhook">Webhook</option>
          <option value="employee">员工调用</option>
        </select>
      </div>

      <div class="swc-actions">
        <button type="button" class="swc-go" :disabled="busy" @click="startAgentLoop">
          {{ busy ? '启动中…' : '开始让 AI 写脚本' }}
        </button>
      </div>
    </section>

    <!-- ===================== Loop / Sandbox 阶段 ===================== -->
    <section v-else class="swc-runtime">
      <aside class="swc-chat">
        <header class="swc-chat-head">
          <h2>对话</h2>
          <span v-if="loopRunning" class="swc-running">运行中…</span>
          <span v-else-if="outcome?.ok" class="swc-ok">已通过自动验收</span>
          <span v-else-if="outcome" class="swc-bad">未通过</span>
        </header>
        <ol class="swc-events">
          <li v-for="(ev, idx) in events" :key="idx" :class="`ev-${ev.type}`">
            <strong>{{ eventLabel(ev) }}</strong>
            <template v-if="ev.type === 'plan'">
              <p class="swc-plan-summary">{{ formatPlanMdForDisplay(ev.payload?.plan_md) }}</p>
              <details v-if="planMdHasMermaid(ev.payload?.plan_md)" class="swc-plan-mermaid">
                <summary>查看流程图原文</summary>
                <pre>{{ mermaidExcerpt(ev.payload?.plan_md) }}</pre>
              </details>
            </template>
            <pre v-else-if="['code', 'repair'].includes(ev.type)">{{ trimCode(ev.payload?.code) }}</pre>
            <p v-else-if="ev.type === 'check'">
              {{ ev.payload?.ok ? '静态检查通过' : '失败：' + (ev.payload?.errors || []).join('；') }}
            </p>
            <p v-else-if="ev.type === 'run'">
              {{ ev.payload?.ok ? `成功，产物 ${ev.payload?.outputs?.length || 0} 个` : '失败' }}
              <small v-if="ev.payload?.stderr_tail">{{ tail(ev.payload.stderr_tail, 240) }}</small>
            </p>
            <p v-else-if="ev.type === 'observe'">
              {{ ev.payload?.ok ? '验收通过' : '验收不通过：' + (ev.payload?.reason || '') }}
            </p>
            <p v-else-if="ev.type === 'error'">{{ ev.payload?.reason || '出错' }}</p>
            <p v-else-if="ev.type === 'context'">已收集上下文（输入摘要、SDK 文档）</p>
            <p v-else-if="ev.type === 'done'">已完成。你可以保存为工作流，并进入沙箱试用。</p>
          </li>
        </ol>
        <div v-if="!loopRunning" class="swc-feedback">
          <textarea
            v-model="feedback"
            rows="2"
            :placeholder="
              !sessionId && workflowId
                ? '描述需要改进的方向（AI 会基于现有脚本重新生成）…'
                : '对生成结果不满意？描述一下要改的点，AI 会再来一轮…'
            "
          />
          <button type="button" :disabled="!feedback.trim()" @click="submitFeedback">
            {{ !sessionId && workflowId ? '让 AI 改进此脚本' : '让 AI 再改' }}
          </button>
        </div>
      </aside>

      <main class="swc-main">
        <div class="swc-tabs">
          <button :class="{ active: tab === 'code' }" @click="tab = 'code'">脚本</button>
          <button :class="{ active: tab === 'output' }" @click="tab = 'output'">运行结果</button>
          <button v-if="stage === 'sandbox'" :class="{ active: tab === 'sandbox' }" @click="tab = 'sandbox'">
            沙箱试用
          </button>
        </div>

        <div v-if="tab === 'code'" class="swc-code-pane">
          <pre><code>{{ currentCode || '（暂无脚本）' }}</code></pre>
        </div>

        <div v-else-if="tab === 'output'" class="swc-output-pane">
          <h3>stdout 末段</h3>
          <pre>{{ runStdout || '(无)' }}</pre>
          <h3>stderr 末段</h3>
          <pre>{{ runStderr || '(无)' }}</pre>
          <h3>产物</h3>
          <ul v-if="runOutputs.length">
            <li v-for="o in runOutputs" :key="o.filename">{{ o.filename }} · {{ humanSize(o.size) }}</li>
          </ul>
          <p v-else>暂无</p>
        </div>

        <div v-else-if="tab === 'sandbox'" class="swc-sandbox-pane">
          <p>用真实业务数据手动跑沙箱，确认无误后即可启用。</p>
          <input type="file" multiple @change="onSandboxFilesPicked" />
          <ul v-if="sandboxFiles.length" class="swc-file-list">
            <li v-for="(f, idx) in sandboxFiles" :key="idx">
              {{ f.name }} <span>{{ humanSize(f.size) }}</span>
              <button type="button" class="swc-file-x" @click="sandboxFiles.splice(idx, 1)">×</button>
            </li>
          </ul>
          <button :disabled="sandboxBusy" @click="runManualSandbox">
            {{ sandboxBusy ? '正在跑沙箱…' : '提交并运行' }}
          </button>
          <div v-if="lastSandboxRun" class="swc-sandbox-result">
            <p>
              本次结果：<strong :class="lastSandboxRun.status === 'success' ? 'ok' : 'bad'">{{
                lastSandboxRun.status
              }}</strong>
            </p>
            <pre>stdout: {{ tail(lastSandboxRun.stdout_tail, 1200) }}</pre>
            <pre v-if="lastSandboxRun.stderr_tail">stderr: {{ tail(lastSandboxRun.stderr_tail, 1200) }}</pre>
            <ul v-if="lastSandboxRun.outputs?.length">
              <li v-for="o in lastSandboxRun.outputs" :key="o.filename">
                {{ o.filename }}
                <button type="button" class="swc-download" @click="() => downloadSandboxOutput(o)">
                  下载
                </button>
              </li>
            </ul>
            <button v-if="canActivate" class="swc-activate" @click="activate">满意，启用此工作流</button>
          </div>
        </div>

        <footer v-if="stage === 'loop' && outcome?.ok && !committed" class="swc-commit-bar">
          <input v-model="workflowName" placeholder="给这个脚本工作流起个名字" />
          <button :disabled="!workflowName.trim()" @click="commitToWorkflow">保存为工作流 → 进入沙箱试用</button>
        </footer>
      </main>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
import { getAccessToken } from '../infrastructure/storage/tokenStore'
import { formatPlanMdForDisplay } from '../utils/planMdDisplay'

type Stage = 'brief' | 'loop' | 'sandbox'

interface BriefInput {
  filename: string
  description: string
}

interface AgentEvent {
  type: string
  iteration: number
  payload: any
}

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
const outcome = ref<any>(null)
const loopRunning = ref(false)
const busy = ref(false)
const tab = ref<'code' | 'output' | 'sandbox'>('code')
const committed = ref(false)
const workflowId = ref<number | null>(null)
const workflowName = ref<string>('')
const feedback = ref<string>('')
const sandboxFiles = ref<File[]>([])
const sandboxBusy = ref(false)
const lastSandboxRun = ref<any>(null)
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
  } catch (e: any) {
    events.value.push({ type: 'error', iteration: -1, payload: { reason: e.message || String(e) } })
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
  } catch (e: any) {
    events.value.push({ type: 'error', iteration: -1, payload: { reason: e.message || String(e) } })
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
  } catch (e: any) {
    events.value.push({ type: 'error', iteration: -1, payload: { reason: e.message || String(e) } })
    loopRunning.value = false
  }
}

async function commitToWorkflow() {
  if (!sessionId.value || !workflowName.value.trim()) return
  try {
    const wf: any = await api.commitScriptWorkflowSession(sessionId.value, {
      name: workflowName.value.trim(),
      schema_in: {},
    })
    committed.value = true
    workflowId.value = wf.id
    stage.value = 'sandbox'
    tab.value = 'sandbox'
  } catch (e: any) {
    alert('保存失败：' + (e.message || e))
  }
}

async function runManualSandbox() {
  if (!workflowId.value) return
  sandboxBusy.value = true
  try {
    const r: any = await api.sandboxRunScriptWorkflow(workflowId.value, sandboxFiles.value)
    lastSandboxRun.value = r
  } catch (e: any) {
    alert('沙箱执行失败：' + (e.message || e))
  } finally {
    sandboxBusy.value = false
  }
}

async function downloadSandboxOutput(output: any) {
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
  } catch (e: any) {
    alert('下载失败：' + (e.message || e))
  }
}

async function activate() {
  if (!workflowId.value) return
  try {
    await api.activateScriptWorkflow(workflowId.value)
    router.push({ name: 'workbench-script-workflow-detail', params: { id: workflowId.value } })
  } catch (e: any) {
    alert('启用失败：' + (e.message || e))
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
      const wf: any = await api.getScriptWorkflow(id)
      Object.assign(brief, wf.brief || {})
      workflowId.value = wf.id
      workflowName.value = wf.name
      committed.value = true
      stage.value = 'sandbox'
      tab.value = 'sandbox'
      const runRows: any[] = await api.listScriptWorkflowRuns(wf.id).catch(() => [])
      lastSandboxRun.value = Array.isArray(runRows) && runRows.length ? runRows[0] : null
      events.value = [
        { type: 'context', iteration: 0, payload: { existing: true } },
        { type: 'done', iteration: 0, payload: { code: wf.script_text, outcome: { ok: true, final_code: wf.script_text } } },
      ]
      outcome.value = { ok: true, final_code: wf.script_text }
    } catch (e: any) {
      alert('加载工作流失败：' + (e.message || e))
    }
  }
})
</script>

<style scoped>
.swc { max-width: 1200px; margin: 0 auto; padding: 24px 24px 80px; color: #d8dde6; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
.swc-head { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; margin-bottom: 20px; }
.swc-head h1 { margin: 0; font-size: 20px; flex: 1; }
.swc-back { background: transparent; color: #9aa3b2; border: 1px solid #2c333f; padding: 6px 12px; border-radius: 6px; cursor: pointer; }
.swc-steps { list-style: none; display: flex; gap: 12px; margin: 0; padding: 0; flex-wrap: wrap; }
.swc-steps li { padding: 6px 12px; border: 1px solid #2c333f; border-radius: 999px; font-size: 13px; color: #6b7280; }
.swc-steps li.done { color: #57c785; border-color: #57c785; }
.swc-steps li.active { color: #f5d870; border-color: #f5d870; }

.swc-brief-tip { color: #9aa3b2; line-height: 1.7; padding: 12px 16px; background: #161a22; border-left: 3px solid #f5d870; border-radius: 4px; }
.swc-templates { margin: 16px 0 24px; }
.swc-templates summary { cursor: pointer; color: #c2c8d4; padding: 8px 0; }
.swc-templates-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.swc-template { text-align: left; padding: 12px 14px; background: #161a22; border: 1px solid #2c333f; border-radius: 6px; cursor: pointer; color: #d8dde6; }
.swc-template strong { display: block; margin-bottom: 4px; }
.swc-template span { color: #8b94a4; font-size: 12px; }

.swc-field { margin-bottom: 18px; }
.swc-field label { display: block; margin-bottom: 6px; color: #c2c8d4; font-size: 14px; }
.swc-field .req { color: #f57878; }
.swc-field textarea, .swc-field input[type=text], .swc-field select { width: 100%; background: #0f131a; color: #d8dde6; border: 1px solid #2c333f; border-radius: 6px; padding: 10px 12px; font: inherit; box-sizing: border-box; }
.swc-field textarea { resize: vertical; min-height: 60px; }
.swc-row { display: flex; align-items: center; gap: 12px; }
.swc-row label { margin-bottom: 0; }
.swc-row select { width: auto; }
.swc-hint { color: #f5d870; font-size: 12px; margin: 4px 0 0; }
.swc-file-list { list-style: none; margin: 8px 0 0; padding: 0; }
.swc-file-list li { display: flex; align-items: center; gap: 12px; padding: 6px 0; border-bottom: 1px dashed #2c333f; font-size: 13px; }
.swc-file-name { color: #d8dde6; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.swc-file-size { color: #6b7280; font-size: 11px; }
.swc-file-desc { flex: 1; }
.swc-file-x { background: transparent; border: none; color: #f57878; cursor: pointer; }

.swc-actions { display: flex; justify-content: flex-end; padding: 24px 0 0; border-top: 1px solid #2c333f; margin-top: 24px; }
.swc-go { padding: 12px 24px; background: #f5d870; color: #0b0e14; font-weight: 600; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; }
.swc-go:disabled { opacity: 0.5; cursor: not-allowed; }

.swc-runtime { display: grid; grid-template-columns: 360px 1fr; gap: 20px; min-height: 600px; }
.swc-chat { display: flex; flex-direction: column; background: #0f131a; border: 1px solid #2c333f; border-radius: 8px; max-height: 80vh; }
.swc-chat-head { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid #2c333f; }
.swc-chat-head h2 { margin: 0; font-size: 14px; }
.swc-running { color: #f5d870; font-size: 12px; }
.swc-ok { color: #57c785; font-size: 12px; }
.swc-bad { color: #f57878; font-size: 12px; }
.swc-events { flex: 1; overflow-y: auto; list-style: none; margin: 0; padding: 12px; }
.swc-events li { padding: 8px 10px; margin-bottom: 8px; background: #161a22; border-left: 3px solid #2c333f; border-radius: 4px; font-size: 13px; line-height: 1.6; }
.swc-events li.ev-done { border-color: #57c785; }
.swc-events li.ev-error { border-color: #f57878; }
.swc-events li.ev-check { border-color: #80b3ff; }
.swc-events li strong { display: block; color: #c2c8d4; margin-bottom: 4px; }
.swc-events pre { background: #0b0e14; padding: 8px; border-radius: 4px; overflow-x: auto; max-height: 300px; font-size: 11px; margin: 4px 0 0; }
.swc-events small { display: block; color: #8b94a4; margin-top: 4px; font-size: 11px; }

.swc-feedback { padding: 12px; border-top: 1px solid #2c333f; display: flex; flex-direction: column; gap: 8px; }
.swc-feedback textarea { background: #0b0e14; color: #d8dde6; border: 1px solid #2c333f; border-radius: 4px; padding: 8px; font: inherit; resize: none; }
.swc-feedback button { background: #2c333f; color: #d8dde6; border: none; padding: 8px; border-radius: 4px; cursor: pointer; }
.swc-feedback button:disabled { opacity: 0.5; cursor: not-allowed; }

.swc-main { display: flex; flex-direction: column; background: #0f131a; border: 1px solid #2c333f; border-radius: 8px; overflow: hidden; }
.swc-tabs { display: flex; border-bottom: 1px solid #2c333f; }
.swc-tabs button { flex: 0 0 auto; padding: 10px 18px; background: transparent; border: none; color: #8b94a4; cursor: pointer; }
.swc-tabs button.active { color: #f5d870; border-bottom: 2px solid #f5d870; }
.swc-code-pane { flex: 1; overflow: auto; padding: 12px; }
.swc-code-pane pre { margin: 0; background: #0b0e14; color: #c2c8d4; padding: 16px; border-radius: 4px; font-size: 12px; line-height: 1.6; overflow-x: auto; }
.swc-output-pane { padding: 16px; overflow: auto; }
.swc-output-pane h3 { margin: 0 0 6px; color: #c2c8d4; font-size: 13px; }
.swc-output-pane pre { background: #0b0e14; padding: 8px; border-radius: 4px; font-size: 11px; line-height: 1.5; overflow-x: auto; max-height: 200px; margin: 0 0 16px; }

.swc-sandbox-pane { padding: 16px; overflow: auto; }
.swc-sandbox-pane button { margin-top: 12px; padding: 8px 18px; background: #2c333f; color: #d8dde6; border: none; border-radius: 4px; cursor: pointer; }
.swc-sandbox-pane button:disabled { opacity: 0.5; cursor: not-allowed; }
.swc-sandbox-result { margin-top: 16px; padding: 12px; background: #161a22; border-radius: 6px; }
.swc-sandbox-result .ok { color: #57c785; }
.swc-sandbox-result .bad { color: #f57878; }
.swc-sandbox-result pre { background: #0b0e14; padding: 8px; border-radius: 4px; font-size: 11px; max-height: 200px; overflow-x: auto; margin: 8px 0; }
.swc-download { margin: 0 0 0 8px !important; padding: 3px 8px !important; font-size: 12px; }
.swc-activate { background: #57c785 !important; color: #0b0e14 !important; font-weight: 600; padding: 10px 20px !important; }

.swc-commit-bar { display: flex; gap: 12px; padding: 12px 16px; border-top: 1px solid #2c333f; background: #161a22; }
.swc-commit-bar input { flex: 1; background: #0b0e14; color: #d8dde6; border: 1px solid #2c333f; border-radius: 4px; padding: 8px 12px; }
.swc-commit-bar button { padding: 8px 18px; background: #f5d870; color: #0b0e14; font-weight: 600; border: none; border-radius: 4px; cursor: pointer; }
.swc-commit-bar button:disabled { opacity: 0.5; cursor: not-allowed; }

@media (max-width: 900px) {
  .swc-runtime { grid-template-columns: 1fr; }
}
</style>
