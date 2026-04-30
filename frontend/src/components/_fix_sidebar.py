import os

src = r'E:\FHD\frontend\src\components\Sidebar.vue'
bak = r'E:\FHD\frontend\src\components\Sidebar.vue.bak'

# 读取原文件
with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 备份
with open(bak, 'w', encoding='utf-8') as f:
    f.write(content)

# 添加新菜单项
old_menu = '''const menuItemsBase = [
  { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
  { key: 'ai-ecosystem', name: 'AI生态', iconClass: 'fa-sitemap' },
  { key: 'model-payment', name: '模型支付', iconClass: 'fa-credit-card' },
  { key: 'products', name: '产品管理', iconClass: 'fa-cubes' },
  { key: 'materials', name: '原材料仓库', iconClass: 'fa-archive' },
  { key: 'traditional-mode', name: '传统模式', iconClass: 'fa-table' },
  { key: 'business-docking', name: '业务对接', iconClass: 'fa-exchange' },
  { key: 'orders', name: '订单管理', iconClass: 'fa-file-text-o' },
  { key: 'shipment-records', name: '出货记录', iconClass: 'fa-industry' },
  { key: 'customers', name: '客户管理', iconClass: 'fa-users' },
  { key: 'wechat-contacts', name: '微信联系人列表', iconClass: 'fa-weixin' },
  { key: 'print', name: '标签打印', iconClass: 'fa-print' },
  { key: 'printer-list', name: '打印机列表', iconClass: 'fa-print' },
  { key: 'template-preview', name: '模板库', iconClass: 'fa-file-o' },
  { key: 'settings', name: '系统设置', iconClass: 'fa-cog' },
  { key: 'tools', name: '工具表', iconClass: 'fa-wrench' },
  { key: 'other-tools', name: '员工工作流管理', iconClass: 'fa-sitemap' }
]'''

new_menu = '''const menuItemsBase = [
  { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
  { key: 'ai-ecosystem', name: 'AI生态', iconClass: 'fa-sitemap' },
  { key: 'model-payment', name: '模型支付', iconClass: 'fa-credit-card' },
  { key: 'products', name: '产品管理', iconClass: 'fa-cubes' },
  { key: 'materials', name: '原材料仓库', iconClass: 'fa-archive' },
  { key: 'inventory', name: '库存管理', iconClass: 'fa-database' },  // 已恢复
  { key: 'traditional-mode', name: '传统模式', iconClass: 'fa-table' },
  { key: 'business-docking', name: '业务对接', iconClass: 'fa-exchange' },
  { key: 'orders', name: '订单管理', iconClass: 'fa-file-text-o' },
  { key: 'shipment-records', name: '出货记录', iconClass: 'fa-industry' },
  { key: 'customers', name: '客户管理', iconClass: 'fa-users' },
  { key: 'wechat-contacts', name: '微信联系人列表', iconClass: 'fa-weixin' },
  { key: 'approval-hub', name: '审批中心', iconClass: 'fa-check-square-o' },  // 已恢复
  { key: 'approval-workspace', name: '审批工作台', iconClass: 'fa-desktop' },  // 已恢复
  { key: 'employee-workspace', name: '员工空间', iconClass: 'fa-user-circle' },  // 已恢复
  { key: 'print', name: '标签打印', iconClass: 'fa-print' },
  { key: 'printer-list', name: '打印机列表', iconClass: 'fa-print' },
  { key: 'template-preview', name: '模板库', iconClass: 'fa-file-o' },
  { key: 'settings', name: '系统设置', iconClass: 'fa-cog' },
  { key: 'tools', name: '工具表', iconClass: 'fa-wrench' },
  { key: 'other-tools', name: '员工工作流管理', iconClass: 'fa-sitemap' }
]'''

content = content.replace(old_menu, new_menu)

# 写入
with open(src, 'w', encoding='utf-8') as f:
    f.write(content)

print('Sidebar.vue updated with new menu items!')
print('Added: inventory, approval-hub, approval-workspace, employee-workspace')
