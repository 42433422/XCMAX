import type { AminEmployeePlugin } from '../_types'

const plugin: AminEmployeePlugin = {
  id: 'shipment_mgmt',
  label: '出货管理 AI 员工',
  kind: 'core',
  defaultEnabled: false,
  panelTitle: '工作流 · 出货管理 AI 员工',
  databaseLink: {
    routeName: 'shipment-records',
    label: '查看出货记录数据库',
    description: '出货管理 AI 员工写入的出货记录与审计数据',
  },
  stitchPlacement: { leftPct: 36, topPct: 82, scale: 4.2 },
  flowDoc: {
    lead: '围绕发货单生成、打印与出货记录核对；打印成功后可自动拉取本单位出货记录做统计与审计建议。',
    steps: [
      { label: '启用员工', detail: '副窗开关打开。' },
      { label: '对话触发生成发货单', detail: '预览 → 确认执行 → shipment_generate 写库并生成文档。' },
      { label: '开始打印', detail: '对话或任务卡片触发打印标签/单据。' },
      { label: '打印后审计（启用本员工时）', detail: '请求出货记录列表，汇总条数与今日增量，提示核对、导出 Excel 与推送同事；更新工作流条目与副窗推送。' },
    ],
    notes: ['生成环节已通过 record_store 写入 shipment_records；审计侧重一致性核对与对外同步。'],
  },
}

export default plugin
