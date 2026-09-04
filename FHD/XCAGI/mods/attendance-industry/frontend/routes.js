const modRoutes = [
  {
    path: '/attendance-industry/dashboard',
    name: 'attendance-industry-dashboard',
    component: () => import('./views/DashboardView.vue'),
    meta: { title: '考勤看板', mod: 'attendance-industry' },
  },
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
    id: 'attendance-industry-dashboard',
    label: '考勤看板',
    icon: 'fa-dashboard',
    path: '/attendance-industry/dashboard',
  },
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
