import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'attendance_ai',
  label: '考勤ai助手',
  kind: 'extension',
  defaultEnabled: false,
  flowDoc: {
    lead: '协助处理出勤记录、异常说明与排班相关问答；后续可接入考勤系统 API 与状态轮询。',
    steps: [
      { label: '启用员工', detail: '副窗开关打开。' },
      { label: '接收考勤相关查询', detail: '处理出勤记录查询、异常说明提交与排班问答。' },
    ],
  },
}

export default plugin
