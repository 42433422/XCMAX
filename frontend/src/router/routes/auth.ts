import type { RouteRecordRaw } from 'vue-router'

export const authRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../../views/LoginView.vue'),
    meta: { title: '登录', publicAccess: true, hideChrome: true }
  },
  {
    path: '/lan-gate',
    name: 'lan-gate',
    component: () => import('../../views/LanGateView.vue'),
    meta: { title: '局域网授权', publicAccess: true, hideChrome: true }
  }
]
