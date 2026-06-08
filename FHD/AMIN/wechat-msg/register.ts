import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'wechat_msg',
  label: '微信消息处理 AI 员工',
  kind: 'core',
  defaultEnabled: false,
  panelTitle: '工作流 · 微信消息处理 AI 员工',
  databaseLink: {
    routeName: 'wechat-contacts',
    label: '查看微信联系人',
    description: '微信消息处理 AI 员工监控的星标联系人与会话',
  },
  stitchPlacement: { leftPct: 86, topPct: 82, scale: 4.2 },
  flowDoc: {
    lead: '依赖「星标聊天自动刷新」轮询 work_mode_feed；新消息签名变化时跑意图，并写入对话页任务列表。',
    steps: [
      { label: '副窗启用本员工', detail: '与开关状态持久化 xcagi_workflow_ai_employees。' },
      { label: '智能对话勾选星标自动刷新', detail: '约每分钟拉取星标联系人最新消息。' },
      { label: '定时拉取并副窗推送', detail: '有新消息时助手推送提醒。' },
      { label: '意图预处理', detail: '可开启「专业模式 AI 意图体验」走 /api/ai/intent/test，否则 inferWechatCustomerIntent 本地规则。' },
      { label: '结果写入列表', detail: '派发 xcagi:wechat-ai-task-enqueue，右侧出现「微信消息处理 · 联系人」类条目。' },
    ],
    notes: ['命中发货类话术且同时启用微信或出货管理时，可触发发货单预览任务（xcagi:wechat-shipment-preview-task）。'],
  },
  signalBridges: [
    {
      eventNames: ['xcagi:wechat-ai-task-enqueue'],
      handler(detail) {
        const { useWorkflowAiEmployeesStore } = require('@/stores/workflowAiEmployees')
        const wf = useWorkflowAiEmployeesStore()
        if (!wf.enabled.wechat_msg) return
        const d = detail as Record<string, unknown>
        const name = String(d?.contactName || '星标联系人').trim()
        const msg = String(d?.messageText || '').trim()
        const line = `${name}：${msg.replace(/\s+/g, ' ').slice(0, 120)}`
        const at = Date.now()
        const { useWorkflowEmployeeSpaceStore } = require('@/stores/workflowEmployeeSpace')
        const space = useWorkflowEmployeeSpaceStore()
        space.applyFromWorkflowPayload('工作流 · 微信消息处理 AI 员工', {
          employeeId: 'wechat_msg',
          workflowStageLine: '监控中 · 最近已处理',
          workflowProgressPct: 100,
          workflowProgressLabel: '处理中',
          workflowCurrentHint: `最近一条客户消息已预处理：${line.slice(0, 120)}${line.length > 120 ? '…' : ''}`,
          workflowProgressIdle: false,
          workflowProgressStarted: true,
          lastWechat: { at, line },
        })
      },
    },
    {
      eventNames: ['xcagi:wechat-star-feed-polled'],
      handler(detail) {
        const { useWorkflowAiEmployeesStore } = require('@/stores/workflowAiEmployees')
        const wf = useWorkflowAiEmployeesStore()
        if (!wf.enabled.wechat_msg) return
        const d = detail as Record<string, unknown>
        const { useWorkflowEmployeeSpaceStore } = require('@/stores/workflowEmployeeSpace')
        const space = useWorkflowEmployeeSpaceStore()
        const prev = space.snapshots?.wechat_msg
        const pollOk = d?.ok !== false
        const t = Number(d?.at) || Date.now()
        const sec = Math.max(1, Math.round((Number(d?.intervalMs) || 60000) / 1000))
        const n = d?.contactCount
        const cnt = typeof n === 'number' ? `星标联系人 ${n} 位` : '星标联系人'
        const clock = new Date(t).toLocaleTimeString('zh-CN', { hour12: false })
        const monitorLine = `${pollOk ? '拉取通道正常' : '上次拉取失败，将重试'} · 上次检查 ${clock} · 每 ${sec}s 轮询 · ${cnt}`
        space.applyFromWorkflowPayload(
          prev?.panelTitle || '工作流 · 微信消息处理 AI 员工',
          {
            employeeId: 'wechat_msg',
            workflowStageLine: prev?.stage && prev.stage.includes('已处理') ? prev.stage : '监控中 · 等待新消息',
            workflowProgressPct: prev?.progressPct ?? 30,
            workflowProgressLabel: prev?.progressLabel || '轮询中',
            workflowCurrentHint: monitorLine,
            workflowProgressIdle: false,
            workflowProgressStarted: true,
            lastWechat: prev?.lastWechat || { at: t, line: monitorLine },
          },
        )
      },
    },
  ],
}

export default plugin
