import type { RouteRecordRaw } from 'vue-router'

export const coreRoutes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'chat',
    component: () => import('../../views/ChatView.vue'),
    meta: { title: '智能对话' }
  },
  {
    path: '/xcmax-admin',
    name: 'xcmax-admin',
    component: () => import('../../views/XCmaxAdminView.vue'),
    meta: { title: '服务器后台' }
  }
]
