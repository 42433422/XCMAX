import type { RouteRecordRaw } from 'vue-router'

export const settingsRoutes: RouteRecordRaw[] = [
  {
    path: '/settings',
    name: 'settings',
    component: () => import('../../views/SettingsView.vue'),
    meta: { title: '设置' }
  },
  {
    path: '/desktop-runtime',
    name: 'desktop-runtime',
    component: () => import('../../views/DesktopRuntimeView.vue'),
    meta: { title: '桌面运行时' }
  }
]
