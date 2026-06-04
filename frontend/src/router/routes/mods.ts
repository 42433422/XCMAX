import type { RouteRecordRaw } from 'vue-router'

export const modRoutes: RouteRecordRaw[] = [
  {
    path: '/mod-store',
    name: 'mod-store',
    component: () => import('../../views/ModStore.vue'),
    meta: { title: '扩展市场' }
  },
  {
    path: '/mod/:modId',
    name: 'mod-landing',
    component: () => import('../../views/ModLandingView.vue'),
    meta: { title: 'Mod 详情', mod: true }
  }
]
