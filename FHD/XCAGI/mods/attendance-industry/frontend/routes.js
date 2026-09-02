const modRoutes = [
  {
    path: '/attendance-industry',
    name: 'attendance-industry-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '考勤表转换', mod: 'attendance-industry' },
  },
  {
    path: '/attendance-industry/settings',
    name: 'attendance-industry-settings',
    component: () => import('./views/AttendanceSettingsView.vue'),
    meta: { title: '考勤设置', mod: 'attendance-industry' },
  },
];

const modMenu = [
  {
    id: 'attendance-industry-home',
    label: '考勤表转换',
    icon: 'fa-file-excel-o',
    path: '/attendance-industry',
  },
  {
    id: 'attendance-industry-settings',
    label: '考勤设置',
    icon: 'fa-cog',
    path: '/attendance-industry/settings',
  },
];

export { modRoutes, modMenu };
