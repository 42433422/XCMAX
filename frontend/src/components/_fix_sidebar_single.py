import os
import shutil

src = r'E:\FHD\frontend\src\components\Sidebar.vue'
bak = r'E:\FHD\frontend\src\components\Sidebar.vue.single'

shutil.copy(src, bak)

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 合并审批菜单为单一入口
old_menu = """  { key: 'inventory', name: '库存管理', iconClass: 'fa-database' },  // 已恢复
  { key: 'approval-hub', name: '审批中心', iconClass: 'fa-check-square-o' },  // 已恢复
  { key: 'approval-workspace', name: '审批工作台', iconClass: 'fa-desktop' },  // 已恢复
  { key: 'employee-workspace', name: '员工空间', iconClass: 'fa-user-circle' },  // 已恢复"""

new_menu = """  { key: 'inventory', name: '库存管理', iconClass: 'fa-database' },  // 已恢复
  { key: 'approval-hub', name: '审批中心', iconClass: 'fa-check-square-o' },  // 三合一：工作台+流程管理+规则"""

content = content.replace(old_menu, new_menu)

with open(src, 'w', encoding='utf-8') as f:
    f.write(content)

print("Sidebar fixed with single approval entry!")
