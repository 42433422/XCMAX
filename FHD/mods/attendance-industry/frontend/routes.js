const modRoutes = [
  {
    path: '/attendance-industry/settings',
    name: 'attendance-industry-settings',
    component: () => import('./views/AttendanceSettingsView.vue'),
    meta: { title: '考勤设置', mod: 'attendance-industry' }
  }
];

const modMenu = [];

export { modRoutes, modMenu };
