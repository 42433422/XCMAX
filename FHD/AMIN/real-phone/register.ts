import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'real_phone',
  label: '真实电话业务员',
  kind: 'fixed_extension',
  defaultEnabled: false,
  databaseLink: {
    routeName: 'chat',
    label: '回到智能对话查看通话进度',
    description: '真实电话业务员的 ADB 链路状态与任务面板均在对话页',
  },
  flowDoc: {
    lead: '【固定扩展】员工 id 固定为 real_phone，由前端写死。流程对齐「微信电话对接业务员」的执行粒度，差异在于通话入口改为 ADB（安卓真机）链路。',
    steps: [
      { label: '启用员工', detail: '副窗开关打开；关闭时停止 ADB 电话链路。' },
      { label: 'ADB 设备连通检查', detail: '检查 adb 连接状态、目标设备在线与通话权限；异常时提示重连与授权。' },
      { label: '来电检测与自动接听', detail: '监听来电状态（振铃/接通/挂断）；命中规则后执行接听动作，失败重试并记录原因。' },
      { label: '通话音频采集与 ASR', detail: '接通后采集通话音频并实时转写，提取客户诉求、关键信息与上下文。' },
      { label: '意图生成与回复播报', detail: '基于话术与意图结果生成回复，执行 TTS 播报；必要时保留人工接管入口。' },
      { label: '结果回写与状态同步', detail: '将摘要、跟进建议与异常信息写入任务面板，并与工作流状态轮询同步。' },
    ],
    notes: ['若部署的是特定 Mod 的真实线路实现，仍以该 Mod 的 API 约定与能力位为准。'],
  },
}

export default plugin
