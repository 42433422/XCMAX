const modRoutes = [
  {
    path: '/taiyangniao-pro',
    name: 'taiyangniao-pro-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '考勤表转换', mod: 'taiyangniao-pro' }
  }
];

const modMenu = [
  {
    id: 'taiyangniao-pro-home',
    label: '考勤表转换',
    icon: 'fa-file-excel-o',
    path: '/taiyangniao-pro'
  }
];

export { modRoutes, modMenu };
