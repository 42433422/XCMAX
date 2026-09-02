// 兼容 façade：全站页面知识库已按职责域拆分（共享类型 / 官网域 / 市场域 / 跨域汇总），
// 本文件保留原导出面，内部逻辑与原单体行为完全一致。
export {
  CORP_LINKS,
  isContactPagePath,
  resolveCorpPageId,
  getCorpPageKnowledge,
  getCorpWelcomeDesc,
  getCorpWelcomeTitle,
  getCorpQuickActions,
  linkForCorpPage,
} from './siteKnowledge/corpPages'
export {
  getMarketPageKnowledge,
  getMarketQuickActions,
  getMarketWelcomeDesc,
} from './siteKnowledge/marketRoutes'
export { getStructuredPageSummary } from './siteKnowledge/pageSummary'
export type { IntakeTaskType, QuickAction, PageKnowledge } from './siteKnowledge/types'
