/** 页面知识共享类型（原 siteKnowledge 单体拆分） */

export type IntakeTaskType = 'intake_fill' | 'intake_step' | 'intake_review' | 'navigate'

export interface QuickAction {
  label: string
  message?: string
  task?: IntakeTaskType
  payload?: { stepId?: string; prompt?: string; href?: string }
}

export interface PageKnowledge {
  pageId: string
  title: string
  description: string
  /** KiKi 欢迎区主标题 */
  welcomeTitle?: string
  /** 管家空状态欢迎语（省略则用 summary 首句） */
  welcomeDesc?: string
  summary: string
  highlights: string[]
  quickActions: QuickAction[]
}
