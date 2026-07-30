# 侧栏能力闭环复测（源码后端）2026-07-24

从：**智能对话** · 用户：wuxinghua1 · stamp=95006
页面：16/16
失败：无

- [x] 智能对话 checks 5/5
  - LOOP OK 对话写入读回: ai_chat=200 save=200 found=True
  - OK GET /api/conversations/cl-chat-95006 -> 200
  - OK POST /api/ai/chat -> 200
  - OK POST /api/chat/send -> 200
  - OK POST /api/conversations/cl-chat-95006/messages -> 200
  - OK GET /api/conversations/cl-chat-95006 -> 200

- [x] 信息 checks 6/6
  - LOOP OK IM发消息读回: send=200 found=True
  - OK GET /api/im/conversations -> 200
  - OK GET /api/im/contacts -> 200
  - OK GET /api/im/unread-total -> 200
  - OK POST /api/im/conversations/direct -> 200
  - OK POST /api/im/conversations/1/messages -> 200
  - OK GET /api/im/conversations/1/messages -> 200

- [x] AI群聊 checks 4/4
  - LOOP OK 建群发消息读回: create=200 send=200 found=True
  - OK GET /api/mobile/v1/ai-groups -> 200
  - OK POST /api/mobile/v1/ai-groups -> 200
  - OK POST /api/mobile/v1/ai-groups/479a7812a9574919a77180a9987ea28d/messages -> 200
  - OK GET /api/mobile/v1/ai-groups/479a7812a9574919a77180a9987ea28d/messages -> 200

- [x] 智能生态 checks 6/6
  - OK GET /api/platform-shell/capabilities -> 200
  - OK GET /api/mods/ -> 200
  - OK GET /api/mods/routes -> 200
  - OK GET /api/aiopen/manifest -> 200
  - OK GET /api/aiopen/guide -> 200
  - OK GET /api/aiopen/panel -> 200

- [x] 知识库 checks 7/7
  - LOOP OK 知识可读+可写: ingest=200 query=200 rag_may_be_off
  - OK GET /api/knowledge/v1/health -> 200
  - OK GET /api/knowledge/v1/datasets -> 200
  - OK GET /api/knowledge/v1/datasets/persy-knowledge/status?include_documents=false -> 200
  - OK GET /api/knowledge -> 200
  - OK GET /api/persy/knowledge -> 200
  - OK POST /api/knowledge/v1/datasets/persy-knowledge/documents -> 200
  - OK POST /api/knowledge/v1/datasets/persy-knowledge/query -> 200

- [x] 员工工作台 checks 4/4
  - OK GET /api/system/workflow-employee-catalog -> 200
  - OK GET /api/workflow-employee-space/overview -> 200
  - OK GET /api/mod/xcagi-core-workflow-employees/status -> 200
  - OK GET /api/mod/xcagi-workflow-visualization-bridge/status -> 200

- [x] 业务对象 checks 4/4
  - LOOP OK 产品创建读回: found=True
  - OK GET /api/mod/xcagi-erp-domain-bridge/products/list -> 200
  - OK POST /api/mod/xcagi-erp-domain-bridge/products/add -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/products/list -> 200
  - OK GET /api/products/list -> 200

- [x] 组织管理 checks 4/4
  - LOOP OK 组织创建读回: found_list=True found_root=True before=5 after=6 root=6
  - OK GET /api/customers/list -> 200
  - OK POST /api/customers -> 200
  - OK GET /api/customers/list -> 200
  - OK GET /api/customers -> 200

- [x] 业务单据 checks 3/3
  - LOOP OK 订单可读/可建: list=200 create=201
  - OK GET /api/orders -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/orders -> 200
  - OK POST /api/orders -> 201

- [x] 业务记录 checks 3/3
  - OK GET /api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/units -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/shipment/shipment-records/records -> 200
  - OK GET /api/shipment/shipment-records/units -> 200

- [x] 资源库 checks 3/3
  - LOOP OK 物料创建: found=True status=200
  - OK GET /api/materials -> 200
  - OK POST /api/materials -> 200
  - OK GET /api/materials -> 200

- [x] 数据来源 checks 4/4
  - OK GET /api/data-sources -> 200
  - OK GET /api/wechat_contacts/decrypt_status -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/wechat/contacts -> 200
  - OK GET /api/mod/xcagi-erp-domain-bridge/status -> 200

- [x] 模板与打印 checks 4/4
  - OK GET /api/templates -> 200
  - OK GET /api/excel/templates -> 200
  - OK GET /api/print/templates -> 200
  - OK GET /api/document-templates -> 200

- [x] 打印机列表 checks 3/3
  - LOOP OK 本机打印机可见: count=1 names=['Canon_TS3700_series']
  - OK GET /api/printers -> 200
  - OK GET /api/print/printers -> 200
  - OK GET /api/print/validate -> 200

- [x] 模板库 checks 1/1
  - OK GET /api/document-templates -> 200

- [x] 系统设置 checks 5/5
  - OK GET /api/workspace/prefs -> 200
  - OK GET /api/system/industry -> 200
  - OK GET /api/desktop/status -> 200
  - OK GET /api/mods/ -> 200
  - OK GET /api/system/industries -> 200

