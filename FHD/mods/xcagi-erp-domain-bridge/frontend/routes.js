/**
 * 里程碑 K+ / O+：ERP 业务页 — 物理视图在 Mod 包内。
 */

import { modView } from '@/router/modViews'

const MOD_ID = 'xcagi-erp-domain-bridge'
const PREFIX = `/mod/${MOD_ID}`

function route(pathSuffix, name, viewFile, title) {
  return {
    path: `${PREFIX}${pathSuffix}`,
    name,
    component: modView(MOD_ID, viewFile),
    meta: { title, mod: MOD_ID },
  }
}

const modRoutes = [
  route('/products', 'mod-erp-products', 'ProductsView.vue', '业务对象'),
  route('/customers', 'mod-erp-customers', 'CustomersView.vue', '组织管理'),
  route('/orders', 'mod-erp-orders', 'OrdersView.vue', '业务单据'),
  route('/orders/create', 'mod-erp-orders-create', 'CreateOrderView.vue', '新建业务单据'),
  route('/shipment-records', 'mod-erp-shipment-records', 'ShipmentRecordsView.vue', '业务记录'),
  // wechat-contacts 已移至 xcagi-wechat-bridge Mod
  route('/materials', 'mod-erp-materials', 'MaterialsView.vue', '资源库'),
  { path: `${PREFIX}/materials-list`, name: 'mod-erp-materials-list', redirect: `${PREFIX}/materials` },
  route('/traditional-mode', 'mod-erp-traditional-mode', 'TraditionalModeView.vue', '表格模式'),
// 旧「业务对接」页已退役；数据对接中心由宿主 EtlCenterView（/business-docking）承担
  { path: `${PREFIX}/business-docking`, name: 'mod-erp-business-docking', redirect: '/business-docking' },
  route('/data-sources', 'mod-erp-data-sources', 'DataSourcesView.vue', '数据来源'),
  route('/print', 'mod-erp-print', 'PrintView.vue', '标签输出与打印'),
  route('/printer-list', 'mod-erp-printer-list', 'PrinterListView.vue', '打印机列表'),
  route('/template-preview', 'mod-erp-template-preview', 'TemplatePreviewView.vue', '模板库'),
  route('/label-editor', 'mod-erp-label-editor', 'LabelEditorView.vue', '标签编辑器'),
  route('/purchase', 'mod-erp-purchase', 'PurchaseView.vue', '采购管理'),
  route('/inventory', 'mod-erp-inventory', 'InventoryView.vue', '库存管理'),
  route('/batch-analyze', 'mod-erp-batch-analyze', 'BatchAnalyzeView.vue', '批量分析'),
]

const modMenu = [
  { id: 'mod-erp-products', label: '业务对象', icon: 'fa-cubes', path: `${PREFIX}/products` },
  { id: 'mod-erp-customers', label: '组织管理', icon: 'fa-users', path: `${PREFIX}/customers` },
  { id: 'mod-erp-orders', label: '业务单据', icon: 'fa-file-text-o', path: `${PREFIX}/orders` },
  { id: 'mod-erp-shipment-records', label: '业务记录', icon: 'fa-industry', path: `${PREFIX}/shipment-records` },
  { id: 'mod-erp-materials', label: '资源库', icon: 'fa-archive', path: `${PREFIX}/materials` },
  { id: 'mod-erp-traditional-mode', label: '表格模式', icon: 'fa-table', path: `${PREFIX}/traditional-mode` },
  { id: 'mod-erp-business-docking', label: '数据对接中心', icon: 'fa-exchange', path: `${PREFIX}/business-docking` },
  { id: 'mod-erp-data-sources', label: '数据来源', icon: 'fa-database', path: `${PREFIX}/data-sources` },
  { id: 'mod-erp-print', label: '标签输出与打印', icon: 'fa-print', path: `${PREFIX}/print` },
  { id: 'mod-erp-printer-list', label: '打印机列表', icon: 'fa-print', path: `${PREFIX}/printer-list` },
  { id: 'mod-erp-template-preview', label: '模板库', icon: 'fa-file-o', path: `${PREFIX}/template-preview` },
]

export { modRoutes, modMenu }
