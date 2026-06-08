// 考勤行业包 — 须导出名为 modRoutes 的路由数组（供 XCAGI registerModRoutes 识别）

const modRoutes = [
  {
    path: '/attendance-industry',
    name: 'attendance-industry-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '考勤行业包', mod: 'attendance-industry' }
  },
  {
    path: '/attendance-industry/settings',
    name: 'attendance-industry-settings',
    component: () => import('./views/AttendanceSettingsView.vue'),
    meta: { title: '考勤设置', mod: 'attendance-industry' }
  }
];

const modMenu = [
  {
    id: 'attendance-industry-home',
    label: '考勤表转换',
    icon: 'fa-file-excel-o',
    path: '/attendance-industry'
  }
];

export { modRoutes, modMenu };
