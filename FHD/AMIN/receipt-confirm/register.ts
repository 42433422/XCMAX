import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'receipt_confirm',
  label: '收货确认 AI 员工',
  kind: 'core',
  defaultEnabled: false,
  panelTitle: '工作流 · 收货确认 AI 员工',
  databaseLink: {
    routeName: 'customers',
    label: '查看客户管理数据库',
    description: '收货确认 AI 员工跟进的客户业务进程与历史反馈',
  },
  stitchPlacement: { leftPct: 62, topPct: 82, scale: 4.2 },
  flowDoc: {
    lead: '与微信消息员工共用星标轮询与意图规则；客户消息命中收货、到货、签收、对账等时，将联系人及业务进程摘要写入本工作流，便于内部在对话中跟进。',
    steps: [
      { label: '启用员工', detail: '副窗开关打开。' },
      { label: '星标消息 → 意图预处理（同源）', detail: '与微信员工相同链路；命中 isReceiptConfirmRelatedWechatIntent 后派发 xcagi:workflow-receipt-feedback-signal。' },
      { label: '面板展示客户业务进程', detail: '工作流条目中展示摘要；可结合智能对话继续确认、对账或转交。' },
    ],
    notes: ['仅开收货确认、未开微信员工时仍会跑星标意图用于本链路，但不会写入「微信消息处理」列表项。'],
  },
  signalBridges: [
    {
      eventNames: ['xcagi:workflow-receipt-feedback-signal'],
      handler(detail) {
        const { useWorkflowAiEmployeesStore } = require('@/stores/workflowAiEmployees')
        const wf = useWorkflowAiEmployeesStore()
        if (!wf.enabled.receipt_confirm) return
        const d = detail as Record<string, unknown>
        const line = String(d?.line || '').trim() || '客户反馈'
        const at = Number(d?.at) || Date.now()
        const hint = [
          d?.contactName ? `联系人：${d.contactName}` : '',
          d?.intentLabel ? `意图：${d.intentLabel}` : '',
          d?.messageText ? `摘要：${String(d.messageText).slice(0, 120)}` : '',
        ]
          .filter(Boolean)
          .join(' · ')
        const { useWorkflowEmployeeSpaceStore } = require('@/stores/workflowEmployeeSpace')
        const space = useWorkflowEmployeeSpaceStore()
        space.applyFromWorkflowPayload('工作流 · 收货确认 AI 员工', {
          employeeId: 'receipt_confirm',
          workflowStageLine: '已收客户侧业务进程反馈',
          workflowProgressPct: 55,
          workflowProgressLabel: '进行中',
          workflowCurrentHint: hint || line,
          workflowProgressIdle: false,
          workflowProgressStarted: true,
          lastReceiptFeedback: { at, line, detail: hint },
        })
      },
    },
  ],
}

export default plugin
