// __MOD_NAME__ — 须导出名为 modRoutes 的路由数组（供 XCAGI registerModRoutes 识别）

const modRoutes = [
  {
    path: '/__MOD_ID__',
    name: '__MOD_ID__-home',
    component: () => import('./views/HomeView.vue'),
    meta: { title: '__MOD_NAME__', mod: '__MOD_ID__' }
  }
];

const modMenu = [
  {
    id: '__MOD_ID__-home',
    label: '__MOD_NAME__',
    icon: 'fa-cube',
    path: '/__MOD_ID__'
  }
];

const modShell = {
  uiShell: 'config/ui_shell.json',
  settings: {
    defaultIndustry: '通用',
    industryOptions: ['通用']
  },
  makeScene: {
    title: '将__MOD_NAME__做成可运行工作流',
    description: '先澄清需求，再生成执行清单、制作草稿与校验报告。'
  }
};

export { modRoutes, modMenu, modShell };
