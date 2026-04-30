import os
import shutil

src = r'E:\FHD\frontend\src\components\Sidebar.vue'
bak = r'E:\FHD\frontend\src\components\Sidebar.vue.new'

# 备份
shutil.copy(src, bak)

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 添加新菜单项
old_menu = """  { key: 'other-tools', name: '员工工作流管理', iconClass: 'fa-sitemap' }
]"""

new_menu = """  { key: 'inventory', name: '库存管理', iconClass: 'fa-database' },  // 已恢复
  { key: 'approval-hub', name: '审批中心', iconClass: 'fa-check-square-o' },  // 已恢复
  { key: 'approval-workspace', name: '审批工作台', iconClass: 'fa-desktop' },  // 已恢复
  { key: 'employee-workspace', name: '员工空间', iconClass: 'fa-user-circle' },  // 已恢复
  { key: 'other-tools', name: '员工工作流管理', iconClass: 'fa-sitemap' }
]"""

content = content.replace(old_menu, new_menu)

# 写入临时文件
with open(bak, 'w', encoding='utf-8') as f:
    f.write(content)

# 替换
os.remove(src)
os.rename(bak, src)

print("Sidebar.vue fixed!")
