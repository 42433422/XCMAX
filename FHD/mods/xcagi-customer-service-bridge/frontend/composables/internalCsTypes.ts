/** 内部客服工作台共享类型 */

export type EnterpriseUserRow = {
  id: number
  username: string
  isEnterprise?: boolean
  hasPipeline?: boolean
  bindingCount?: number
  is_enterprise?: boolean
  has_pipeline?: boolean
}

export type ClientSummary = {
  stage: string
  last_message_preview: string
  intake_sent: boolean
  /** 表单联网检索 / ERP 关联后的完整公司名（非登录账号） */
  display_name: string
}

export type IntakeFormFields = {
  name?: string
  email?: string
  phone?: string
  company?: string
  message?: string
  desktop_os?: string
  need_mobile?: boolean
}

export type MarketUserPickerRow = {
  id: number
  username: string
  email?: string
  is_enterprise?: boolean
  has_pipeline?: boolean
}

export type ClientSummaries = Record<number, ClientSummary>

/** 客户 pipeline 读写所需字段（其余字段由工作台持有） */
export type PipelineReadShape = {
  stage: string
  username: string
  last_message_preview: string
  intake_sent: boolean
  intake_form: IntakeFormFields | null
  erp_customer_name: string
}