import type { RouteRecordRaw } from 'vue-router'

export const aiRoutes: RouteRecordRaw[] = [
  {
    path: '/ai-ecosystem',
    name: 'ai-ecosystem',
    component: () => import('../../views/AIEcosystemView.vue'),
    meta: { title: '智能生态' }
  },
  {
    path: '/brain',
    name: 'brain',
    component: () => import('../../views/BrainView.vue'),
    meta: { title: '智脑集成' }
  },
  {
    path: '/model-payment',
    name: 'model-payment',
    component: () => import('../../views/ModelPaymentView.vue'),
    meta: { title: '模型服务' }
  },
  {
    path: '/kitten-finance',
    name: 'kitten-finance',
    component: () => import('../../views/KittenFinanceView.vue'),
    meta: { title: '财务分析' }
  }
]
