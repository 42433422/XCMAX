import type { RouteRecordRaw } from 'vue-router';

export const AI_DELIVERY_ROUTES: RouteRecordRaw[] = [
  {
    path: '/brain',
    name: 'brain',
    component: () => import('../views/BrainView.vue'),
    meta: { title: '智脑集成' },
  },
  {
    path: '/private-mod-delivery',
    name: 'private-mod-delivery',
    component: () => import('../views/PrivateModDeliveryView.vue'),
    meta: { title: '生产员工 · 私有交付' },
  },
];
