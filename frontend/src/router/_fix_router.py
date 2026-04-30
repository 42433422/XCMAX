import os

src = r'E:\FHD\frontend\src\router\index.ts'
bak = r'E:\FHD\frontend\src\router\index.ts.bak'

# 读取备份
with open(bak, 'r', encoding='utf-8') as f:
    content = f.read()

# 添加新路由
new_routes = '''  {
    path: '/batch-analyze',
    name: 'batch-analyze',
    component: () => import('../views/BatchAnalyzeView.vue'),
    meta: { title: '批量分析' }
  },
  // 审批中心模块（已恢复）
  {
    path: '/approval-hub',
    name: 'approval-hub',
    component: () => import('../views/ApprovalHubView.vue'),
    meta: { title: '审批中心' }
  },
  {
    path: '/approval-workspace',
    name: 'approval-workspace',
    component: () => import('../views/ApprovalWorkspaceView.vue'),
    meta: { title: '审批工作台' }
  },
  {
    path: '/approval-flow-management',
    name: 'approval-flow-management',
    component: () => import('../views/ApprovalFlowManagementView.vue'),
    meta: { title: '审批流程管理' }
  },
  {
    path: '/approval-rules',
    name: 'approval-rules',
    component: () => import('../views/ApprovalRulesView.vue'),
    meta: { title: '审批规则配置' }
  },
  // 库存管理（已恢复）
  {
    path: '/inventory',
    name: 'inventory',
    component: () => import('../views/InventoryView.vue'),
    meta: { title: '库存管理' }
  },
  // 员工工作流模块（已恢复）
  {
    path: '/employee-workspace',
    name: 'employee-workspace',
    component: () => import('../views/EmployeeWorkspaceView.vue'),
    meta: { title: '员工空间' }
  },
  {
    path: '/yuangong-stitch',
    name: 'yuangong-stitch',
    component: () => import('../views/YuangongStitchFullView.vue'),
    meta: { title: '员工工作流全景' }
  },
  // Mod 详情着陆页（已恢复）
  {
    path: '/mod/:modId',
    name: 'mod-landing',
    component: () => import('../views/ModLandingView.vue'),
    meta: { title: 'Mod 详情', mod: true }
  }
];'''

# 替换旧的路由结尾
old_ending = '''  {
    path: '/batch-analyze',
    name: 'batch-analyze',
    component: () => import('../views/BatchAnalyzeView.vue'),
    meta: { title: '批量分析' }
  }
];'''

content = content.replace(old_ending, new_routes)

# 写入新文件
os.remove(src)
with open(src, 'w', encoding='utf-8') as f:
    f.write(content)

print('Router restored with 9 additional routes!')
