export type PersyNodeTheme = {
  color: string
  border: string
  category: string
  labelColor: string
}

export const PERSY_NODE_THEME: Record<string, PersyNodeTheme> = {

  core: { color: '#17211d', border: '#7ad1a5', category: 'Persy', labelColor: '#17211d' },
  erp_ontology: { color: '#2f3327', border: '#b9c982', category: 'ERP 本体', labelColor: '#2f3327' },
  erp_domain: { color: '#5f6d3f', border: '#c9d69c', category: 'ERP 领域', labelColor: '#48522f' },
  erp_entity: { color: '#60798d', border: '#bdd2df', category: 'ERP 实体', labelColor: '#3e5768' },
  erp_rule: { color: '#786a9d', border: '#d6caef', category: 'ERP 规则', labelColor: '#554775' },
  erp_constraint: { color: '#9c4b46', border: '#efc0bb', category: 'ERP 约束', labelColor: '#70302c' },
  topic: { color: '#2f6f8f', border: '#b9dfef', category: '主题', labelColor: '#244c60' },
  source: { color: '#c56f3d', border: '#f2c6a7', category: '来源', labelColor: '#7a3f20' },
  knowledge: { color: '#268578', border: '#a9ddd5', category: '知识', labelColor: '#1d6259' },
  memory: { color: '#a85667', border: '#efbdc8', category: '记忆', labelColor: '#763846' },
  recall: { color: '#d39a29', border: '#ffe08d', category: '召回', labelColor: '#7f5a13' },
  onboarding: { color: '#ffffff', border: '#9ba9a2', category: '开始', labelColor: '#52625a' },
}
