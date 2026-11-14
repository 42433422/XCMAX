import type { ComputedRef, Ref } from 'vue'

export type PhaseCheckKey =
  | 'bind'
  | 'sync'
  | 'messages'
  | 'connected_welcome'
  | 'intake_sent'
  | 'form_done'
  | 'contract_draft'
  | 'crm_record'
  | 'erp_linked'
  | 'delivery_plan'
  | 'delivery_progress'
  | 'payment_received'
  | 'invoice_issued'

export type PhaseGuide = {
  id: string
  label: string
  headline: string
  description: string
  actionHint?: string
  groupTip?: string
  comingSoon?: string
  checklist: Array<{ key: PhaseCheckKey; text: string }>
}

export const DEFAULT_PIPELINE_STAGES = [
  { id: 'idle', label: '未接触' },
  { id: 'connected', label: '已建联' },
  { id: 'intake', label: '需求采集' },
  { id: 'intake_done', label: '已提交' },
  { id: 'quoted', label: '已报价' },
  { id: 'negotiating', label: '议价' },
  { id: 'contract_pending', label: '待签' },
  { id: 'signed', label: '已签' },
  { id: 'delivering', label: '交付中' },
  { id: 'delivered', label: '已交付' },
]

export const PHASE_GUIDES: Record<string, PhaseGuide> = {
  idle: {
    id: 'idle',
    label: '未接触',
    headline: '建立客户服务通道',
    description: '先确认该客户的跟进方式与档案信息，系统据此跟踪服务进度。',
    checklist: [
      { key: 'bind', text: '已确认客户与其跟进方式' },
      { key: 'sync', text: '已建立客户服务档案' },
    ],
  },
  connected: {
    id: 'connected',
    label: '已建联',
    headline: '建立联系，跟进客户需求',
    description:
      '进入本阶段后，需与客户建立联系并介绍服务。下一阶段「需求采集」起，将向客户发送官网需求表单链接与填写说明（含审核码指引）。',
    actionHint: '确认与客户建立联系后，即可进入下一阶段。',
    checklist: [
      { key: 'bind', text: '已与客户建立联系' },
      { key: 'connected_welcome', text: '已向客户介绍服务（AI 助理自我介绍）' },
      { key: 'sync', text: '已同步最新沟通记录' },
      { key: 'messages', text: '已跟进最近沟通记录' },
    ],
  },
  intake: {
    id: 'intake',
    label: '需求采集',
    headline: '发送表单链接与填写说明',
    description:
      '从本阶段起，请向客户发送官网专属需求表单链接，并说明填写方式与审核码回传。客户提交后可用审核码拉取表单；您也可生成更详细话术后再发。',
    actionHint: '复制表单链接并发送给客户填写；未发送前可重新生成。',
    checklist: [
      { key: 'intake_sent', text: '已向客户介绍服务并发送采集话术/表单链接' },
      { key: 'form_done', text: '需求已在官网表单提交并同步' },
    ],
  },
  intake_done: {
    id: 'intake_done',
    label: '已提交',
    headline: '确认需求，准备报价',
    description: '客户已提交或口头确认需求。请核对范围与交付边界，确认后再发正式报价。',
    actionHint: '用下方话术确认需求；客户回复后点「分析进度」可自动识别进入已报价/议价。',
    groupTip: '报价与议价均通过客户沟通推进，无需等待自动报价模块。',
    checklist: [
      { key: 'form_done', text: '需求已提交或已确认' },
      { key: 'erp_linked', text: '已关联 ERP 客户主数据' },
      { key: 'messages', text: '已核对关键需求点' },
    ],
  },
  quoted: {
    id: 'quoted',
    label: '已报价',
    headline: '跟进报价反馈',
    description: '报价已发出。关注客户回复，若谈价格或折扣请继续沟通并记录让步点。',
    actionHint: '保存为「已报价」后 CRM 会更新报价单状态；还价时请调至「议价」。',
    groupTip: '客户还价时可直接用议价话术回复；达成一致后手动将阶段调至「待签」。',
    checklist: [
      { key: 'crm_record', text: 'CRM 商机与报价单已入库' },
      { key: 'erp_linked', text: '已关联 ERP 客户' },
      { key: 'messages', text: '已跟进报价反馈' },
    ],
  },
  negotiating: {
    id: 'negotiating',
    label: '议价',
    headline: '议价沟通，调整方案或价格',
    description: '正在谈价格或交付条件。保持回复及时，关键让步与最终口径保留在沟通记录中。',
    actionHint: '保存为「议价」后 CRM 报价单标记为议价中；谈妥后进入「待签」生成合同。',
    groupTip: '议价以沟通记录为准，发送前请核对金额与范围。',
    checklist: [
      { key: 'crm_record', text: 'CRM 报价单状态为议价中' },
      { key: 'messages', text: '议价要点已对齐' },
    ],
  },
  contract_pending: {
    id: 'contract_pending',
    label: '待签',
    headline: '填写合同并生成 Word',
    description: '乙方信息已预填（成都修茈科技）。填写甲方与金额，生成合同发给客户签署。',
    actionHint: '必填：甲方名称、合同总金额。生成后可下载 Word 并复制发送话术。',
    checklist: [
      { key: 'contract_draft', text: '已生成合同草案' },
      { key: 'messages', text: '已发送合同并跟进' },
    ],
  },
  signed: {
    id: 'signed',
    label: '已签',
    headline: '启动交付计划',
    description: '合同已签。请填写客户期望交付时间与制作里程碑，保存后进入「交付中」阶段。',
    actionHint: '填写预计交付日期并保存计划；可向客户同步首次交付说明。',
    checklist: [
      { key: 'contract_draft', text: '合同已生成或已签署' },
      { key: 'delivery_plan', text: '已填写预计交付时间与里程碑' },
    ],
  },
  delivering: {
    id: 'delivering',
    label: '交付中',
    headline: '定制软件制作进行中',
    description: '按里程碑更新制作进度，定期向客户同步；客户到款后系统自动生成账单。',
    actionHint: '勾选已完成里程碑并保存；进度可同步给客户。检测到款后点「检查到款并出账」。',
    groupTip: '进度以里程碑为准，建议每完成一阶段向客户通报一次。',
    checklist: [
      { key: 'delivery_progress', text: '制作进度已更新并同步客户' },
      { key: 'payment_received', text: '已确认到款' },
      { key: 'invoice_issued', text: '已自动生成账单' },
    ],
  },
  delivered: {
    id: 'delivered',
    label: '已交付',
    headline: '交付完成，售后跟进',
    description: '项目已验收交付。确认到款与账单无误后，持续响应售后咨询。',
    actionHint: '若尚未出账，可再次「检查到款并出账」；验收问题持续跟进。',
    checklist: [
      { key: 'delivery_progress', text: '全部里程碑已完成' },
      { key: 'invoice_issued', text: '账单已出具' },
      { key: 'messages', text: '验收与售后已跟进' },
    ],
  },
}

/** 清单全满足会自动进入下一阶段（与后端 auto_advance_pipeline 一致） */
export const AUTO_ADVANCE_CHECKLIST_STAGES = new Set(['idle', 'connected', 'intake'])

type PipelineStageId = { id: string; label: string }

/**
 * 阶段相关纯函数/常量。pipelineStages 与 currentStageId 由父组件注入，
 * 保持与原本地定义完全一致的行为。
 */
export function usePipelineGuide(
  pipelineStages: Ref<Array<PipelineStageId>>,
  currentStageId: ComputedRef<string>,
) {
  function stageRank(stageId: string) {
    return pipelineStages.value.findIndex((s) => s.id === stageId)
  }

  function stageLabel(stageId: string) {
    return pipelineStages.value.find((s) => s.id === stageId)?.label
      || DEFAULT_PIPELINE_STAGES.find((s) => s.id === stageId)?.label
      || stageId
  }

  function stageGuideFor(stageId: string) {
    return PHASE_GUIDES[stageId] || PHASE_GUIDES.idle
  }

  function stepperItemClass(stageId: string, _idx: number) {
    const cur = stageRank(currentStageId.value)
    const si = stageRank(stageId)
    if (stageId === currentStageId.value) return 'is-current'
    if (si >= 0 && si < cur) return 'is-done'
    return ''
  }

  return { stageLabel, stageGuideFor, stageRank, stepperItemClass }
}