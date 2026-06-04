import type { RouteRecordRaw } from 'vue-router'

export const businessRoutes: RouteRecordRaw[] = [
  {
    path: '/products',
    name: 'products',
    component: () => import('../../views/ProductsView.vue'),
    meta: { title: '产品管理' }
  },
  {
    path: '/materials',
    name: 'materials',
    component: () => import('../../views/ServerFunctionsView.vue'),
    meta: { title: '物料管理' }
  },
  {
    path: '/materials-list',
    name: 'materials-list',
    component: () => import('../../views/MaterialsView.vue'),
    meta: { title: '物料列表' }
  },
  {
    path: '/orders',
    name: 'orders',
    component: () => import('../../views/OrdersView.vue'),
    meta: { title: '订单管理' }
  },
  {
    path: '/orders/create',
    name: 'orders-create',
    component: () => import('../../views/CreateOrderView.vue'),
    meta: { title: '新建订单' }
  },
  {
    path: '/shipment-records',
    name: 'shipment-records',
    component: () => import('../../views/ShipmentRecordsView.vue'),
    meta: { title: '发货记录' }
  },
  {
    path: '/customers',
    name: 'customers',
    component: () => import('../../views/CustomersView.vue'),
    meta: { title: '客户管理' }
  },
  {
    path: '/data-sources',
    name: 'data-sources',
    component: () => import('../../views/DataSourcesView.vue'),
    meta: { title: '数据来源' }
  },
  {
    path: '/wechat-contacts',
    name: 'wechat-contacts',
    component: () => import('../../views/WechatContactsView.vue'),
    meta: { title: '企业微信联系人' }
  },
  {
    path: '/business-docking',
    name: 'business-docking',
    component: () => import('../../views/BusinessDockingView.vue'),
    meta: { title: '业务对接' }
  },
  {
    path: '/inventory',
    name: 'inventory',
    component: () => import('../../views/InventoryView.vue'),
    meta: { title: '库存管理' }
  },
  {
    path: '/purchase',
    name: 'purchase',
    component: () => import('../../views/PurchaseView.vue'),
    meta: { title: '耗材申领' }
  }
]
