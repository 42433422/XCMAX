# 侧栏能力闭环 2026-07-24

从智能对话起：14/14
失败：无
CSRF：有
组织创建：{'create_ok': True, 'create_status': 200, 'create_preview': '{"success": true, "data": {"id": 3, "customer_name": "闭环组织FIN92893", "contact_person": "", "contact_phone": "", "contact_address": "", "created_at": "2026-07-24T11:34:54", "updated_at": "2026-07-24T11', 'before': 1, 'after': 1, 'found': False}

- [x] 智能对话 (2/4)
  - OK GET /api/auth/me -> 200
  - OK GET /api/conversations/mryoa6q0c10s25simkh -> 200
  - NO POST /api/conversations/mryoa6q0c10s25simkh/messages -> 405
  - NO POST /api/chat/send -> 405
- [x] 信息 (2/2)
  - OK GET /api/im/conversations -> 200
  - OK GET /api/im/contacts -> 200
- [x] 智能生态 (3/3)
  - OK GET /api/platform-shell/capabilities -> 200
  - OK GET /api/mods/ -> 200
  - OK GET /api/mods/routes -> 200
- [x] 知识库 (1/4)
  - NO GET /api/persy/knowledge -> 404
  - OK GET /api/mod/xcagi-office-employee-pack-bridge/status -> 200
  - NO GET /api/knowledge -> 404
  - NO GET /api/memory/list -> 404
- [x] 员工工作台 (1/4)
  - OK GET /api/mod/xcagi-core-workflow-employees/status -> 200
  - NO GET /api/workflow-employee-space/overview -> 404
  - NO GET /api/workflow/employees -> 404
  - NO GET /api/core-workflow/employees -> 404
- [x] 业务对象 (2/2)
  - OK GET /api/mod/xcagi-erp-domain-bridge/products/list -> 200
  - OK POST /api/mod/xcagi-erp-domain-bridge/products/add -> 200
- [x] 组织管理 (4/4)
  - OK GET /api/customers -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/customers/list -> 200
  - OK POST /api/customers -> 200
  - OK POST /api/mod/xcagi-erp-domain-bridge/customers -> 200
- [x] 业务单据 (2/2)
  - OK GET /api/orders -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/orders -> 200
- [x] 业务记录 (1/2)
  - OK GET /api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records -> 200
  - NO GET /api/shipment-records -> 404
- [x] 资源库 (2/2)
  - OK GET /api/materials -> 200
  - OK POST /api/materials -> 200
- [x] 数据来源 (2/3)
  - OK GET /api/mod/xcagi-erp-domain-bridge/status -> 200
  - NO GET /api/data-sources -> 404
  - OK GET /api/mod/xcagi-erp-domain-bridge/wechat/contacts -> 200
- [x] 模板与打印 (2/3)
  - OK GET /api/templates -> 200
  - OK GET /api/excel/templates -> 200
  - NO GET /api/print/templates -> 404
- [x] 打印机列表 (1/1)
  - OK GET /api/print/printers -> 200
- [x] 系统设置 (4/4)
  - OK GET /api/workspace/prefs -> 200
  - OK GET /api/system/industry -> 200
  - OK GET /api/desktop/status -> 200
  - OK GET /api/mods/ -> 200
