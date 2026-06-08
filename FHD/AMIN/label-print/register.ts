import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'label_print',
  label: '标签打印 AI 员工',
  kind: 'core',
  defaultEnabled: false,
  panelTitle: '工作流 · 标签打印 AI 员工',
  databaseLink: {
    routeName: 'print',
    label: '查看标签打印工作台',
    description: '与标签打印 AI 员工对应的打印模板与打印任务工作台',
  },
  stitchPlacement: { leftPct: 14, topPct: 82, scale: 4.2 },
  flowDoc: {
    lead: '仅接收星标链路中识别到的「标签/打印」意图信号；未命中前任务面板进度为 0，不计为已执行。',
    steps: [
      { label: '启用员工', detail: '副窗开关打开。' },
      { label: '星标消息 → 意图预处理', detail: '与微信员工共用同一轮询与意图逻辑；命中后派发 xcagi:workflow-label-print-signal。' },
      { label: '对话补充并打印', detail: '在智能对话发送型号、张数等，结合打印机与模板配置执行打印链路。' },
    ],
    notes: ['仅开标签员工、未开微信员工时仍会跑星标意图用于发信号，但不会写入微信意图列表项。'],
  },
  signalBridges: [
    {
      eventNames: ['xcagi:workflow-label-print-signal'],
      handler(detail) {
        const { useWorkflowAiEmployeesStore } = require('@/stores/workflowAiEmployees')
        const wf = useWorkflowAiEmployeesStore()
        if (!wf.enabled.label_print) return
        const line = String((detail as Record<string, unknown>)?.line || '').trim() || '标签/打印类消息'
        const at = Number((detail as Record<string, unknown>)?.at) || Date.now()
        const { useWorkflowEmployeeSpaceStore } = require('@/stores/workflowEmployeeSpace')
        const space = useWorkflowEmployeeSpaceStore()
        space.applyFromWorkflowPayload('工作流 · 标签打印 AI 员工', {
          employeeId: 'label_print',
          workflowStageLine: '已收微信侧标签/打印信号',
          workflowProgressPct: 55,
          workflowProgressLabel: '进行中',
          workflowCurrentHint: `最近命中标签/打印意图：${line.slice(0, 160)}${line.length > 160 ? '…' : ''}`,
          workflowProgressIdle: false,
          workflowProgressStarted: true,
          lastLabelPrint: { at, line },
        })
      },
    },
  ],
}

export default plugin
