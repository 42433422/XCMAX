const workspace = () => import('./views/AttendanceWorkspaceView.vue');

const modRoutes = [
  {
    path: '/attendance-industry',
    name: 'attendance-industry-workspace',
    component: workspace,
    props: { section: 'personnel' },
    meta: { title: '考勤工作区', mod: 'attendance-industry' },
  },
  ...[
    ['personnel', 'personnel', '人员管理'],
    ['departments', 'departments', '部门管理'],
    ['schedules', 'schedules', '排班资源'],
    ['records', 'records', '考勤记录'],
    ['convert', 'home', '考勤表转换'],
    ['settings', 'settings', '考勤设置'],
  ].map(([section, name, title]) => ({
    path: `/attendance-industry/${section}`,
    name: `attendance-industry-${name}`,
    component: workspace,
    props: { section },
    meta: { title: `考勤工作区 · ${title}`, mod: 'attendance-industry' },
  })),
  {
    path: '/attendance-industry/dashboard',
    redirect: { name: 'attendance-industry-workspace' },
  },
];

const modMenu = [
  {
    id: 'attendance-industry-workspace',
    label: '考勤工作区',
    icon: 'fa-calendar',
    path: '/attendance-industry',
  },
];

export { modRoutes, modMenu };
