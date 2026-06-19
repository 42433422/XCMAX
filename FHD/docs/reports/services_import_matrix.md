# services 依赖矩阵

> v10 线内迭代 · 由 `scripts/dev/generate_services_import_matrix.py` 生成

- services 模块数：**100**
- 引用 `app.services` 的 importer 组：**65**

## 按域分组（services 模块）

### auth

- `auth_service` — 2 importer(s)
- `session_service` — 4 importer(s)
- `user_service` — 2 importer(s)

### conversation

- `ai_conversation_service` — 2 importer(s)
- `bert_intent_service` — 1 importer(s)
- `conversation.api` — 16 importer(s)
- `conversation.context` — 16 importer(s)
- `conversation.handlers` — 16 importer(s)
- `conversation.intent` — 16 importer(s)
- `conversation.llm_adapter` — 16 importer(s)
- `conversation.manager` — 16 importer(s)
- `conversation.modstore_adapter` — 16 importer(s)
- `conversation.prompts` — 16 importer(s)
- `conversation_service` — 1 importer(s)
- `deepseek_intent_service` — 1 importer(s)
- `distilled_intent_service` — 0 importer(s)
- `hybrid_intent_service` — 0 importer(s)
- `intent_confirmation_service` — 1 importer(s)
- `intent_service` — 3 importer(s)
- `intent_trainer` — 0 importer(s)
- `train_intent` — 0 importer(s)
- `unified_intent_recognizer` — 4 importer(s)
- `wechat_contact_cache_import` — 1 importer(s)
- `wechat_contact_service` — 0 importer(s)
- `wechat_group_customer_bridge` — 9 importer(s)
- `wechat_passive_group_monitor` — 7 importer(s)
- `wechat_task_service` — 0 importer(s)

### document

- `document_templates.analyzer` — 8 importer(s)
- `document_templates.crud` — 8 importer(s)
- `document_templates.renderer` — 8 importer(s)
- `document_templates.variables` — 8 importer(s)
- `document_templates_service` — 1 importer(s)
- `kitten_ai_document.generate` — 5 importer(s)
- `kitten_ai_document.pickup` — 5 importer(s)
- `skills.label_template_generator.label_template_generator` — 2 importer(s)

### finance

- `contract_lifecycle` — 6 importer(s)
- `finance_unified_archive` — 4 importer(s)
- `service_contract_fill` — 0 importer(s)
- `tax_invoice_provider` — 1 importer(s)

### infra

- `database_service` — 0 importer(s)

### mod

- `mod_zip_normalize` — 1 importer(s)
- `modstore_library_sync` — 1 importer(s)

### ocr

- `ocr_service` — 2 importer(s)
- `paddle_ocr_runner` — 0 importer(s)

### other

- `ai_action_audit_service` — 0 importer(s)
- `data_analysis_service` — 1 importer(s)
- `distillation_data_collector` — 0 importer(s)
- `distillation_trainer` — 0 importer(s)
- `extract_log_service` — 1 importer(s)
- `kitten_business_snapshot` — 3 importer(s)
- `kitten_report.chart_data_service` — 5 importer(s)
- `kitten_report.docx_export` — 5 importer(s)
- `kitten_report.financial_plugins` — 5 importer(s)
- `kitten_report.plugins` — 5 importer(s)
- `kitten_report.save_service` — 5 importer(s)
- `kitten_report.service` — 5 importer(s)
- `mobile_push` — 2 importer(s)
- `operations_line_bridge` — 1 importer(s)
- `purchase_service` — 2 importer(s)
- `rasa_nlu_service` — 0 importer(s)
- `report_service` — 1 importer(s)
- `rule_engine` — 0 importer(s)
- `service_optimizers` — 0 importer(s)
- `system_service` — 0 importer(s)
- `task_agent` — 3 importer(s)
- `task_context_service` — 0 importer(s)
- `tts_service` — 2 importer(s)
- `unified_query_service` — 2 importer(s)
- `user_memory_service` — 1 importer(s)
- `user_preference_service` — 6 importer(s)
- `xcmax_sync_service` — 6 importer(s)

### product

- `ai_product_parser` — 0 importer(s)
- `catalog_client` — 1 importer(s)
- `catalog_visibility` — 1 importer(s)
- `inventory_service` — 1 importer(s)
- `materials_service` — 1 importer(s)
- `product_import_service` — 2 importer(s)
- `products_service` — 1 importer(s)

### shipment

- `printer_service` — 2 importer(s)
- `shipment_number_mode_service` — 0 importer(s)
- `tools_execution.order_parser` — 9 importer(s)
- `tools_execution.order_parser_helpers` — 9 importer(s)

### tools

- `tools_execution.context` — 9 importer(s)
- `tools_execution.executor` — 9 importer(s)
- `tools_execution.registry` — 9 importer(s)
- `tools_execution_service` — 1 importer(s)
- `tools_payload_legacy` — 1 importer(s)
- `tools_workflow_registered` — 2 importer(s)

### user_cs

- `user_cs_change_request` — 0 importer(s)
- `user_cs_connected_welcome` — 0 importer(s)
- `user_cs_crm_store` — 5 importer(s)
- `user_cs_delivery` — 0 importer(s)
- `user_cs_delivery_signoff` — 1 importer(s)
- `user_cs_demand_form` — 0 importer(s)
- `user_cs_enterprise_credentials` — 0 importer(s)
- `user_cs_intake_finalize` — 0 importer(s)
- `user_cs_intake_notice` — 0 importer(s)
- `user_cs_landing_crm` — 0 importer(s)
- `user_cs_pipeline` — 4 importer(s)
- `user_cs_software_delivery` — 0 importer(s)

## Importer → services（Wave 3 迁移优先级）

| domain | importer | services |
|--------|----------|----------|
| application | `app/application/ai_chat_app_service.py` | `(package)` |
| application | `app/application/ai_chat_app_service.py` | `ai_db_schema_index` |
| application | `app/application/employee_runtime/agent_runner.py` | `conversation` |
| application | `app/application/facades/ai_conversation_facade.py` | `ai_conversation_service` |
| application | `app/application/facades/conversation_facade.py` | `conversation_service` |
| application | `app/application/facades/conversation_facade.py` | `data_analysis_service` |
| application | `app/application/facades/conversation_facade.py` | `user_preference_service` |
| application | `app/application/facades/excel_facade.py` | `(package)` |
| application | `app/application/facades/intent_facade.py` | `bert_intent_service` |
| application | `app/application/facades/inventory_facade.py` | `inventory_service` |
| application | `app/application/facades/inventory_facade.py` | `purchase_service` |
| application | `app/application/facades/inventory_facade.py` | `report_service` |
| application | `app/application/facades/kitten_facade.py` | `kitten_ai_document` |
| application | `app/application/facades/kitten_facade.py` | `kitten_business_snapshot` |
| application | `app/application/facades/kitten_facade.py` | `kitten_report` |
| application | `app/application/facades/ocr_facade.py` | `ocr_service` |
| application | `app/application/facades/print_facade.py` | `printer_service` |
| application | `app/application/facades/query_facade.py` | `unified_query_service` |
| application | `app/application/facades/session_facade.py` | `(package)` |
| application | `app/application/facades/session_facade.py` | `session_service` |
| application | `app/application/facades/template_facade.py` | `(package)` |
| application | `app/application/facades/template_facade.py` | `document_templates_service` |
| application | `app/application/facades/tools_facade.py` | `tools_execution_service` |
| application | `app/application/facades/tts_facade.py` | `(package)` |
| application | `app/application/facades/tts_facade.py` | `tts_service` |
| application | `app/application/facades/wechat_facade.py` | `wechat_contact_cache_import` |
| application | `app/application/im_app_service.py` | `xcmax_sync_service` |
| application | `app/application/intent_recognition_app.py` | `intent_service` |
| application | `app/application/kitten_planner_context.py` | `kitten_business_snapshot` |
| application | `app/application/mobile_push_app_service.py` | `mobile_push` |
| application | `app/application/mod_store_catalog_app.py` | `catalog_client` |
| application | `app/application/mod_store_catalog_app.py` | `catalog_visibility` |
| application | `app/application/mod_store_catalog_app.py` | `mod_zip_normalize` |
| application | `app/application/mod_store_catalog_app.py` | `modstore_library_sync` |
| application | `app/application/modstore_conversation_app.py` | `conversation` |
| application | `app/application/normal_chat_dispatch.py` | `customers_service` |
| application | `app/application/planner_compat_service.py` | `conversation` |
| application | `app/application/print_app_service.py` | `printer_service` |
| application | `app/application/product_import_app_service.py` | `product_import_service` |
| application | `app/application/tenant_workspace_prefs.py` | `user_preference_service` |
| application | `app/application/tools/workflow.py` | `kitten_ai_document` |
| application | `app/application/tools/workflow.py` | `unified_query_service` |
| application | `app/application/workflow/planner.py` | `task_agent` |
| application | `app/application/xcmax_sync_app.py` | `xcmax_sync_service` |
| bootstrap.py | `app/bootstrap.py` | `extract_log_service` |
| bootstrap.py | `app/bootstrap.py` | `materials_service` |
| bootstrap.py | `app/bootstrap.py` | `product_import_service` |
| bootstrap.py | `app/bootstrap.py` | `products_service` |
| di | `app/di/registry.py` | `auth_service` |
| di | `app/di/registry.py` | `session_service` |
| di | `app/di/registry.py` | `user_preference_service` |
| di | `app/di/registry.py` | `user_service` |
| domain | `app/domain/services/conversation/coordinator.py` | `intent_service` |
| domain | `app/domain/services/conversation/coordinator.py` | `task_agent` |
| enterprise | `app/enterprise/mod_entitlements.py` | `session_service` |
| fastapi_routes | `app/fastapi_routes/contract_lifecycle_api.py` | `contract_lifecycle` |
| fastapi_routes | `app/fastapi_routes/contract_lifecycle_api.py` | `esign_adapter` |
| fastapi_routes | `app/fastapi_routes/contract_lifecycle_api.py` | `fadada_fasc_client` |
| fastapi_routes | `app/fastapi_routes/contract_lifecycle_api.py` | `stub_esign_store` |
| fastapi_routes | `app/fastapi_routes/contract_lifecycle_api.py` | `user_cs_pipeline` |
| fastapi_routes | `app/fastapi_routes/finance_invoices_api.py` | `finance_unified_archive` |
| fastapi_routes | `app/fastapi_routes/finance_invoices_api.py` | `tax_invoice_provider` |
| fastapi_routes | `app/fastapi_routes/finance_invoices_api.py` | `user_cs_crm_store` |
| fastapi_routes | `app/fastapi_routes/finance_invoices_api.py` | `user_cs_pipeline` |
| fastapi_routes | `app/fastapi_routes/finance_unified_ledger.py` | `finance_unified_archive` |
| fastapi_routes | `app/fastapi_routes/gdpr.py` | `feature_flag` |
| fastapi_routes | `app/fastapi_routes/im_routes.py` | `mobile_push` |
| fastapi_routes | `app/fastapi_routes/operations_line_api.py` | `contract_expiry_scheduler` |
| fastapi_routes | `app/fastapi_routes/operations_line_api.py` | `operations_line_bridge` |
| fastapi_routes | `app/fastapi_routes/operations_line_api.py` | `reconciliation_scheduler` |
| fastapi_routes | `app/fastapi_routes/operations_line_api.py` | `user_cs_delivery_signoff` |
| fastapi_routes | `app/fastapi_routes/payment_reconcile_internal_api.py` | `fhd_payment_reconciliation` |
| fastapi_routes | `app/fastapi_routes/private_db_read_assistant_compat.py` | `wechat_decrypt_autoconfig` |
| fastapi_routes | `app/fastapi_routes/private_db_read_assistant_compat.py` | `wechat_decrypt_http` |
| fastapi_routes | `app/fastapi_routes/private_db_read_assistant_compat.py` | `wechat_group_customer_bridge` |
| fastapi_routes | `app/fastapi_routes/user_cs_wechat_passive_compat.py` | `wechat_passive_group_monitor` |
| fastapi_routes | `app/fastapi_routes/wechat_decrypt_routes.py` | `wechat_decrypt_autoconfig` |
| fastapi_routes | `app/fastapi_routes/wechat_decrypt_routes.py` | `wechat_decrypt_http` |
| fastapi_routes | `app/fastapi_routes/xcagi_compat_chat_helpers.py` | `conversation` |
| fastapi_routes | `app/fastapi_routes/xcmax_admin.py` | `admin_sync_service` |
| fastapi_routes | `app/fastapi_routes/xcmax_admin.py` | `wechat_group_customer_bridge` |
| infrastructure | `app/infrastructure/llm/providers/openai_compatible_provider.py` | `conversation` |
| infrastructure | `app/infrastructure/skills/label_template_generator/label_template_generator.py` | `skills` |
| mod_sdk | `app/mod_sdk/mod_employee_llm.py` | `ai_conversation_service` |
| mod_sdk | `app/mod_sdk/services.py` | `unified_intent_recognizer` |
| mod_sdk | `app/mod_sdk/tts.py` | `tts_service` |
| neuro_bus | `app/neuro_bus/integrations/intent_integration.py` | `unified_intent_recognizer` |
| services | `app/services/conversation/context.py` | `kitten_business_snapshot` |
| services | `app/services/conversation/manager.py` | `deepseek_intent_service` |
| services | `app/services/conversation/manager.py` | `intent_confirmation_service` |
| services | `app/services/conversation/manager.py` | `intent_service` |
| services | `app/services/conversation/manager.py` | `task_agent` |
| services | `app/services/conversation/manager.py` | `unified_intent_recognizer` |
| services | `app/services/conversation/manager.py` | `user_memory_service` |
| services | `app/services/conversation/manager.py` | `user_preference_service` |
| services | `app/services/document_templates/__init__.py` | `document_templates` |
| services | `app/services/document_templates/analyzer.py` | `document_templates` |
| services | `app/services/document_templates/analyzer.py` | `skills` |
| services | `app/services/document_templates/crud.py` | `document_templates` |
| services | `app/services/kitten_ai_document/__init__.py` | `kitten_ai_document` |
| services | `app/services/skills/label_template_generator/label_template_generator.py` | `ocr_service` |
| services | `app/services/tools_execution/__init__.py` | `tools_execution` |
| services | `app/services/tools_execution/__init__.py` | `tools_workflow_registered` |
| services | `app/services/tools_execution/executor.py` | `tools_execution` |
| services | `app/services/tools_execution/executor.py` | `tools_payload_legacy` |
| services | `app/services/tools_execution/executor.py` | `tools_workflow_registered` |
| services | `app/services/tools_execution/order_parser.py` | `tools_execution` |
| wechat | `app/fastapi_routes/domains/wechat/routes.py` | `wechat_decrypt_autoconfig` |
| wechat | `app/fastapi_routes/domains/wechat/routes.py` | `wechat_group_customer_bridge` |
| wechat | `app/fastapi_routes/domains/wechat/routes.py` | `wechat_passive_group_monitor` |
