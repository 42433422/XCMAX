import os
import shutil

src = r'E:\FHD\frontend\src\views\ApprovalHubView.vue'
bak = r'E:\FHD\frontend\src\views\ApprovalHubView.vue.new'

shutil.copy(src, bak)

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 更新 tabs 配置（使用嵌套路由的路径）
old_tabs = '''const tabs = [
  { name: 'approval-workspace', label: '工作台', icon: 'fa-tasks' },
  { name: 'approval-flow-management', label: '流程管理', icon: 'fa-sitemap' },
  { name: 'approval-rules', label: '流程规则', icon: 'fa-check-square-o' }
] as const'''

new_tabs = '''const tabs = [
  { name: 'approval-workspace', label: '工作台', icon: 'fa-tasks' },
  { name: 'approval-flow-management', label: '流程管理', icon: 'fa-sitemap' },
  { name: 'approval-rules', label: '流程规则', icon: 'fa-check-square-o' }
] as const

// 嵌套路由的相对路径映射
const routePathMap: Record<string, string> = {
  'approval-workspace': 'workspace',
  'approval-flow-management': 'flow-management',
  'approval-rules': 'rules'
}'''

content = content.replace(old_tabs, new_tabs)

# 修改 RouterLink 使用 path 而不是 name
old_link = ':to="{ name: tab.name }"'
new_link = ':to="`/approval-hub/${routePathMap[tab.name]}`"'

content = content.replace(old_link, new_link)

with open(src, 'w', encoding='utf-8') as f:
    f.write(content)

print("ApprovalHubView fixed!")
