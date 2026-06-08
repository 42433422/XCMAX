import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'wechat_phone',
  label: '微信电话对接业务员',
  kind: 'fixed_extension',
  defaultEnabled: false,
  databaseLink: {
    routeName: 'chat',
    label: '回到智能对话查看通话进度',
    description: '微信电话对接业务员的状态轮询与任务面板均在对话页',
  },
  flowDoc: {
    lead: '【固定扩展】员工 id 固定为 wechat_phone，由前端写死展示名，不是 manifest 动态追加行。启用后调用当前环境绑定的 phone-agent：Win32 监控微信来电、接听、采集、ASR、意图、TTS、VB-Cable。',
    steps: [
      { label: '启用员工', detail: '副窗开关打开；关闭时 POST …/stop。' },
      { label: '启动 phone-agent', detail: '开启时 POST /api/mod/sz-qsm-pro/phone-agent/start。' },
      { label: '轮询运行状态', detail: '启用后约每 15s GET /api/mod/sz-qsm-pro/phone-agent/status。' },
      { label: '来电侧链路', detail: '窗口监控可用 → 来电尝试自动点击接听 → 音频采集 → ASR → 意图 → TTS → VB-Cable。' },
    ],
    notes: ['与四名内置 AI 不同：不依赖星标消息 feed。若 status 异常请检查对应 Mod 服务是否部署。'],
  },
}

export default plugin
