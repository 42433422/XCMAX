// 太阳鸟pro — 须导出名为 modRoutes 的路由数组（供 XCAGI registerModRoutes 识别）

const modRoutes = [
  {
    path: '/taiyangniao-pro',
    name: 'taiyangniao-pro-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '太阳鸟pro', mod: 'taiyangniao-pro' }
  }
];

const modMenu = [
  {
    id: 'taiyangniao-pro-home',
    label: '太阳鸟pro',
    icon: 'fa-cube',
    path: '/taiyangniao-pro'
  }
];

export { modRoutes, modMenu };
