/**
 * 数字管家虚拟员工档案。
 *
 * 与真实员工包对齐：管家也表示成 ``{id, name, manifest: { employee_config_v2 }}``
 * 的结构，``cognition.skills`` 与 ``actions.handlers`` 字段直接被
 * `AdminDutyEmployeeGraph` 的「能做什么 · 怎么做」面板复用，避免单独写一套
 * 渲染分支。
 *
 * 不进 ``catalog_items``：管家是前端常驻智能体，不会被 ``listEmployees`` /
 * ``getEmployeeManifest`` / ``adminEmployeeExecutionCapabilities`` 三个后端
 * 接口返回，因此在值班图里把它作为 ``source='virtual'`` 的合成行注入，
 * 并跳过对应的网络调用。
 */

export const BUTLER_VIRTUAL_AREA_ID = 'ai-butler'
export const BUTLER_VIRTUAL_AREA_LABEL = '前台数字管家'
export const BUTLER_VIRTUAL_AREA_COLOR = '#22d3ee'
export const BUTLER_VIRTUAL_EMPLOYEE_ID = 'xc-digital-butler'

export type EmployeeSkillView = {
  name: string
  brief: string
  kind: string
  /** 该技能在「怎么做」一栏要展示的执行通道：内部 handler / 路由 / API。 */
  how?: string
}

export type EmployeeCapabilityView = {
  /** identity.role.persona — 一句话身份说明 */
  persona: string
  /** identity.role.expertise[] — 擅长领域 */
  expertise: string[]
  /** cognition.skills[] — 可执行技能列表 */
  skills: EmployeeSkillView[]
  /** actions.handlers — 底层 handler 频道 */
  handlers: string[]
  /** collaboration.workflow.workflow_id — 关联工作流 */
  workflowId: number
  /** depends_on — 协作依赖 */
  dependsOn: string[]
  /** 是否为虚拟（前端合成）员工 */
  virtual: boolean
}

export const BUTLER_PROFILE = {
  id: BUTLER_VIRTUAL_EMPLOYEE_ID,
  name: '数字管家',
  area: BUTLER_VIRTUAL_AREA_ID,
  industry: '平台前台',
  source: 'virtual' as const,
  manifest: {
    id: BUTLER_VIRTUAL_EMPLOYEE_ID,
    name: '数字管家',
    version: '1.0.0',
    description: '常驻浏览器的全站 AI 助手，解释页面、引导操作、调度 vibe-coding 改写。',
    artifact: 'butler_runtime',
    employee_config_v2: {
      identity: {
        id: BUTLER_VIRTUAL_EMPLOYEE_ID,
        name: '数字管家',
        version: '1.0.0',
        artifact: 'butler_runtime',
        description:
          '前端常驻 AI 智能体。监听 vue-router、读取当前页面 DOM，可串接 vibe-coding 编排与员工任务总线。',
      },
      cognition: {
        agent: {
          system_prompt:
            '你是 XC AGI 数字管家，平台的全站智能助手。你的职责：引导用户在 ai-store / wallet / workbench 等页面完成操作，并通过 function calling 触发导航/点击/填表/vibe-coding 编排。',
          role: {
            name: '数字管家',
            persona: '熟悉整站路由与控件的浏览器内 AI 助手，跨页持续陪伴。',
            tone: 'professional',
            expertise: ['页面导航', '操作引导', 'AI 员工撮合', 'vibe-coding 改写编排'],
          },
          model: { provider: 'auto', model_name: 'auto', temperature: 0.7, max_tokens: 4000 },
          behavior_rules: [
            '低风险动作（导航、读取）直接执行；中风险（点击、填表）展示预览；高风险（支付、改代码）必须用户明确确认。',
            '永远不要主动替用户完成付款，只引导到对应页面。',
          ],
        },
        skills: [
          {
            name: '页面导航',
            brief: '跳到 plans / ai-store / wallet / recharge / account / workbench 等任意路由。',
            kind: 'navigate',
            how: 'navigate handler · vue-router push',
          },
          {
            name: '页面阅读与解释',
            brief: '把当前 DOM 摘要喂给 /api/agent/butler/chat，回答「这页是什么」。',
            kind: 'read',
            how: 'read handler · pageSerializer + butler chat',
          },
          {
            name: '点击 / 填表',
            brief: '通过 data-butler-id / aria-label 定位元素并模拟用户操作。',
            kind: 'action',
            how: 'click + fill handler · data-butler-id 锚点',
          },
          {
            name: 'Vibe-Coding 改写',
            brief: '把目标 Mod / 工作流 / 员工包丢进编排管线进行原地改写，可回滚。',
            kind: 'orchestrate',
            how: 'POST /api/agent/butler/orchestrate → 轮询 /api/workbench/sessions/{id}',
          },
          {
            name: '搜索 AI 员工',
            brief: '理解需求并跳到 ai-store 列表，并附加筛选 query。',
            kind: 'skill',
            how: 'searchEmployeeSkill · 路由 ai-store + query',
          },
          {
            name: '钱包充值导引',
            brief: '把用户带到 wallet/recharge 并填写金额建议。',
            kind: 'skill',
            how: 'walletRechargeSkill · 路由 wallet-recharge',
          },
          {
            name: '会员订阅引导',
            brief: '解释 plans 档位差异并指引到 plans 页订阅。',
            kind: 'skill',
            how: 'purchasePlanSkill · 路由 plans',
          },
          {
            name: '员工任务发布',
            brief: '订阅 xc-butler-task-broadcast-v1 总线，接收值班图发布的任务并代为处理。',
            kind: 'skill',
            how: 'butlerTaskBus · BroadcastChannel + 内部 EventTarget',
          },
          {
            name: 'QQ 入口',
            brief: '以 QQ 官方机器人身份在群/单聊里收发消息，复用同一套 butler chat 链路。',
            kind: 'channel',
            how: 'butler_qq_bridge · /api/agent/butler/qq/webhook + api.sgroup.qq.com',
          },
        ],
      },
      actions: {
        handlers: [
          'butler_chat',
          'butler_navigate',
          'butler_read_page',
          'butler_click',
          'butler_fill',
          'butler_orchestrate',
          'butler_qq',
          'butler_skill',
        ],
      },
      collaboration: { workflow: { workflow_id: 0 }, depends_on: [] },
      commerce: { industry: '平台前台', price: 0 },
      metadata: { framework_version: '2.0.0', created_by: 'frontend-runtime' },
    },
  },
} as const

const HANDLER_FRIENDLY_LABELS: Record<string, string> = {
  echo: '直接复述输入（仅占位，无 LLM）',
  webhook: '通过 Webhook 触发外部系统',
  llm_md: '调用大模型生成 Markdown',
  llm_json: '调用大模型生成结构化 JSON',
  llm_code: '调用大模型生成代码片段',
  search: '调用研究/搜索工具',
  workflow: '通过工作流（workflow_id）执行',
  vibe: '通过 vibe-coding 改写',
  shell: '执行 shell 命令（高风险，需审批）',
  ops: '调用运维 ops handler（高风险）',
  butler_chat: 'POST /api/agent/butler/chat',
  butler_navigate: 'vue-router push（前端）',
  butler_read_page: '前端 DOM 摘要 + /api/agent/butler/chat',
  butler_click: '在当前页面 click（前端）',
  butler_fill: '在当前页面 fill（前端）',
  butler_orchestrate: 'POST /api/agent/butler/orchestrate',
  butler_skill: '本地 skillRegistry · agentSkillRegistry',
  butler_qq: 'QQ 官方机器人 V2（webhook 入站 + api.sgroup.qq.com 出站）',
}

export function describeHandler(name: string): string {
  return HANDLER_FRIENDLY_LABELS[name] ?? name
}

/**
 * 从 ``manifest`` 中按 V2 schema 抽取「能做什么 · 怎么做」展示模型。
 * - ``cognition.skills[]``、``identity.role.persona/expertise[]``、
 *   ``actions.handlers[]``、``collaboration.workflow.workflow_id`` /
 *   ``collaboration.depends_on``
 * - 兼容老版 manifest（无 ``employee_config_v2``）：从顶层 ``actions``、
 *   ``description`` 兜底。
 */
export function extractEmployeeCapabilityView(
  manifest: Record<string, unknown> | null | undefined,
): EmployeeCapabilityView {
  const empty: EmployeeCapabilityView = {
    persona: '',
    expertise: [],
    skills: [],
    handlers: [],
    workflowId: 0,
    dependsOn: [],
    virtual: false,
  }
  if (!manifest || typeof manifest !== 'object') return empty

  const v2 = (manifest.employee_config_v2 ?? null) as Record<string, unknown> | null
  const cognition = (v2?.cognition ?? null) as Record<string, unknown> | null
  const agent = (cognition?.agent ?? null) as Record<string, unknown> | null
  const role = (agent?.role ?? null) as Record<string, unknown> | null
  const collab = (v2?.collaboration ?? null) as Record<string, unknown> | null
  const wf = (collab?.workflow ?? null) as Record<string, unknown> | null

  const skillsRaw = Array.isArray(cognition?.skills) ? (cognition?.skills as unknown[]) : []
  const skills: EmployeeSkillView[] = []
  for (const s of skillsRaw) {
    if (!s || typeof s !== 'object') continue
    const row = s as Record<string, unknown>
    const name = String(row.name ?? '').trim()
    if (!name) continue
    skills.push({
      name,
      brief: String(row.brief ?? row.description ?? '').trim(),
      kind: String(row.kind ?? '').trim(),
      how: typeof row.how === 'string' ? (row.how as string) : undefined,
    })
  }

  const handlersV2 = (v2?.actions ?? null) as Record<string, unknown> | null
  const handlersTop = (manifest.actions ?? null) as Record<string, unknown> | null
  const handlersList = Array.isArray(handlersV2?.handlers)
    ? (handlersV2!.handlers as unknown[])
    : Array.isArray(handlersTop?.handlers)
      ? (handlersTop!.handlers as unknown[])
      : []
  const handlers = handlersList.map((h) => String(h ?? '').trim()).filter(Boolean)

  const expertiseRaw = Array.isArray(role?.expertise) ? (role?.expertise as unknown[]) : []
  const expertise = expertiseRaw.map((x) => String(x ?? '').trim()).filter(Boolean)

  const dependsTopRaw = Array.isArray(manifest.depends_on) ? (manifest.depends_on as unknown[]) : []
  const dependsV2Raw = Array.isArray(collab?.depends_on) ? (collab?.depends_on as unknown[]) : []
  const dependsOn = (dependsTopRaw.length ? dependsTopRaw : dependsV2Raw)
    .map((x) => String(x ?? '').trim())
    .filter(Boolean)

  return {
    persona: String(role?.persona ?? agent?.system_prompt ?? '').trim(),
    expertise,
    skills,
    handlers,
    workflowId: Number((wf?.workflow_id as number) ?? 0) || 0,
    dependsOn,
    virtual: false,
  }
}

export function butlerCapabilityView(): EmployeeCapabilityView {
  const view = extractEmployeeCapabilityView(BUTLER_PROFILE.manifest as Record<string, unknown>)
  view.virtual = true
  return view
}
