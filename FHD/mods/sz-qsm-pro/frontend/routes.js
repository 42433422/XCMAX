const modRoutes = [
  {
    path: '/qsm-pro',
    name: 'qsm-pro-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '奇士美 PRO', mod: 'sz-qsm-pro' },
  },
  {
    path: '/sz-qsm-pro',
    name: 'sz-qsm-pro-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '奇士美 PRO', mod: 'sz-qsm-pro' },
  },
];

const modMenu = [
  {
    id: 'qsm-pro-home',
    label: '奇士美工作台',
    icon: 'fa-paint-brush',
    path: '/qsm-pro',
  },
];

export { modRoutes, modMenu };
