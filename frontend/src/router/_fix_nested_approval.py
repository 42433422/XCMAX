import os
import shutil

src = r'E:\FHD\frontend\src\router\index.ts'
bak = r'E:\FHD\frontend\src\router\index.ts.nested'

shutil.copy(src, bak)

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 将审批路由改为嵌套结构
old_approval = '''  // 审批中心模块（已恢复）
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
  },'''

new_approval = '''  // 审批中心模块（已恢复）- 三合一嵌套路由
  {
    path: '/approval-hub',
    name: 'approval-hub',
    component: () => import('../views/ApprovalHubView.vue'),
    meta: { title: '审批中心' },
    redirect: { name: 'approval-workspace' },
    children: [
      {
        path: 'workspace',
        name: 'approval-workspace',
        component: () => import('../views/ApprovalWorkspaceView.vue'),
        meta: { title: '审批工作台' }
      },
      {
        path: 'flow-management',
        name: 'approval-flow-management',
        component: () => import('../views/ApprovalFlowManagementView.vue'),
        meta: { title: '审批流程管理' }
      },
      {
        path: 'rules',
        name: 'approval-rules',
        component: () => import('../views/ApprovalRulesView.vue'),
        meta: { title: '审批规则配置' }
      }
    ]
  },'''

content = content.replace(old_approval, new_approval)

# 删除独立的子路由（因为它们现在是子路由了）
# 保留 redirect 确保访问 /approval-workspace 等旧链接也能跳转

with open(src, 'w', encoding='utf-8') as f:
    f.write(content)

print("Router fixed with nested approval routes!")
