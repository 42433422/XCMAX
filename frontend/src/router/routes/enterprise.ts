import type { RouteRecordRaw } from 'vue-router'

export const enterpriseRoutes: RouteRecordRaw[] = [
  {
    path: '/enterprise-customer-service',
    name: 'enterprise-customer-service',
    component: () => import('../../views/EnterpriseCustomerServiceView.vue'),
    meta: { title: '外部客服' }
  }
]
