const modRoutes = [
  {
    path: '/attendance-industry/personnel',
    name: 'attendance-industry-personnel',
    component: () => import('./views/AttendanceManagementView.vue'),
    props: { section: 'personnel' },
    meta: { title: '人员管理', mod: 'attendance-industry' },
  },
  {
    path: '/attendance-industry/departments',
    name: 'attendance-industry-departments',
    component: () => import('./views/AttendanceManagementView.vue'),
    props: { section: 'departments' },
    meta: { title: '部门管理', mod: 'attendance-industry' },
  },
  {
    path: '/attendance-industry/schedules',
    name: 'attendance-industry-schedules',
    component: () => import('./views/AttendanceManagementView.vue'),
    props: { section: 'schedules' },
    meta: { title: '排班资源', mod: 'attendance-industry' },
  },
  {
    path: '/attendance-industry/records',
    name: 'attendance-industry-records',
    component: () => import('./views/AttendanceManagementView.vue'),
    props: { section: 'records' },
    meta: { title: '考勤记录', mod: 'attendance-industry' },
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
  {
    path: '/attendance-industry/dashboard',
    redirect: { name: 'attendance-industry-personnel' },
  },
];

const modMenu = [
  {
    id: 'attendance-industry-personnel',
    label: '人员管理',
    icon: 'fa-user',
    path: '/attendance-industry/personnel',
  },
  {
    id: 'attendance-industry-departments',
    label: '部门管理',
    icon: 'fa-sitemap',
    path: '/attendance-industry/departments',
  },
  {
    id: 'attendance-industry-schedules',
    label: '排班资源',
    icon: 'fa-calendar',
    path: '/attendance-industry/schedules',
  },
  {
    id: 'attendance-industry-records',
    label: '考勤记录',
    icon: 'fa-list-alt',
    path: '/attendance-industry/records',
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
