# 开发工具盘点（规范性「轮子」登记表）

> 由 `scripts/dev/ssot_inventory.py` 生成/维护，**请勿手改**。登记所有规范性
> 守卫/棘轮/校验脚本归属，防止新「轮子」游离于 SSOT 工程外。
> 最后更新：由生成时间戳决定。

| 脚本 | 相对路径 | 角色 | 已纳入 ssot | 依赖 |
|------|----------|------|-------------|------|
| arch_fitness.py | `scripts/arch_fitness.py` | normative | no | stdlib |
| check_3dbs.py | `scripts/archive/2026-07/check_3dbs.py` | guard | no | stdlib |
| check_all_services.py | `scripts/archive/2026-07/check_all_services.py` | guard | no | stdlib |
| check_api_8000.py | `scripts/archive/2026-07/check_api_8000.py` | guard | no | stdlib |
| check_backend_data_source.py | `scripts/archive/2026-07/check_backend_data_source.py` | guard | no | stdlib |
| check_customer_db.py | `scripts/archive/2026-07/check_customer_db.py` | guard | no | stdlib |
| check_customer_unified.py | `scripts/archive/2026-07/check_customer_unified.py` | guard | no | stdlib |
| check_customer_units_count.py | `scripts/archive/2026-07/check_customer_units_count.py` | guard | no | stdlib |
| check_db.py | `scripts/archive/2026-07/check_db.py` | guard | no | stdlib |
| check_db_full.py | `scripts/archive/2026-07/check_db_full.py` | guard | no | stdlib |
| check_db_query.py | `scripts/archive/2026-07/check_db_query.py` | guard | no | stdlib |
| check_db_structure.py | `scripts/archive/2026-07/check_db_structure.py` | guard | no | stdlib |
| check_frontend_statistics.py | `scripts/archive/2026-07/check_frontend_statistics.py` | guard | no | stdlib |
| check_import_status.py | `scripts/archive/2026-07/check_import_status.py` | guard | no | stdlib |
| check_no_xcagi_overrides.py | `scripts/archive/2026-07/check_no_xcagi_overrides.py` | guard | no | stdlib |
| check_purchase_units.py | `scripts/archive/2026-07/check_purchase_units.py` | guard | no | stdlib |
| check_purchase_units_table.py | `scripts/archive/2026-07/check_purchase_units_table.py` | guard | no | stdlib |
| check_templates.py | `scripts/archive/2026-07/check_templates.py` | guard | no | stdlib |
| check_units.py | `scripts/archive/2026-07/check_units.py` | guard | no | stdlib |
| verify_db_copy.py | `scripts/archive/2026-08/verify_db_copy.py` | verify | no | stdlib |
| verify_import.py | `scripts/archive/2026-08/verify_import.py` | verify | no | stdlib |
| check_coverage_ssot.py | `scripts/ci/check_coverage_ssot.py` | ssot | no | stdlib |
| check_operational_errors_gate.py | `scripts/ci/check_operational_errors_gate.py` | guard | no | stdlib |
| guard_temp_scripts.py | `scripts/ci/guard_temp_scripts.py` | guard | no | stdlib |
| verify_admin_console.py | `scripts/deploy/lib/verify_admin_console.py` | verify | no | stdlib |
| verify_release_archive.py | `scripts/deploy/lib/verify_release_archive.py` | verify | no | stdlib |
| check_budget.py | `scripts/dev/check_budget.py` | guard | no | stdlib |
| check_footprint.py | `scripts/dev/check_footprint.py` | guard | no | stdlib |
| check_layer_ratchet.py | `scripts/dev/check_layer_ratchet.py` | guard | no | stdlib |
| check_mod_import_boundaries.py | `scripts/dev/check_mod_import_boundaries.py` | guard | no | stdlib |
| check_requirements_lock.py | `scripts/dev/check_requirements_lock.py` | guard | no | stdlib |
| check_schema_drift.py | `scripts/dev/check_schema_drift.py` | guard | no | stdlib |
| count_big_files.py | `scripts/dev/count_big_files.py` | ratchet | no | stdlib |
| count_coverage_ramp_stubs.py | `scripts/dev/count_coverage_ramp_stubs.py` | ratchet | no | stdlib |
| count_frontend_coverage_stubs.py | `scripts/dev/count_frontend_coverage_stubs.py` | ratchet | no | stdlib |
| count_raw_sql.py | `scripts/dev/count_raw_sql.py` | ratchet | no | stdlib |
| count_type_debt.py | `scripts/dev/count_type_debt.py` | ratchet | no | stdlib |
| coverage_ratchet.py | `scripts/dev/coverage_ratchet.py` | ratchet | yes | stdlib |
| database_storage_ssot.py | `scripts/dev/database_storage_ssot.py` | ssot | yes | stdlib |
| deployment_modes_ssot.py | `scripts/dev/deployment_modes_ssot.py` | ssot | yes | stdlib |
| dev_guards.py | `scripts/dev/dev_guards.py` | normative | yes | stdlib |
| docs_ssot_lint.py | `scripts/dev/docs_ssot_lint.py` | ssot | yes | stdlib |
| guard_coverage_floor.py | `scripts/dev/guard_coverage_floor.py` | guard | no | stdlib |
| guard_mods_inline_ui.py | `scripts/dev/guard_mods_inline_ui.py` | guard | no | stdlib |
| guard_utils_boundary.py | `scripts/dev/guard_utils_boundary.py` | guard | no | stdlib |
| legacy_usage_report.py | `scripts/dev/legacy_usage_report.py` | normative | no | stdlib |
| mods_ssot.py | `scripts/dev/mods_ssot.py` | ssot | yes | stdlib |
| neuro_bus_events_ssot.py | `scripts/dev/neuro_bus_events_ssot.py` | ssot | yes | stdlib |
| prune_stale_branches.py | `scripts/dev/prune_stale_branches.py` | normative | no | stdlib |
| safety_gate.py | `scripts/dev/safety_gate.py` | normative | no | stdlib |
| service_topology_ssot.py | `scripts/dev/service_topology_ssot.py` | ssot | yes | stdlib |
| ssot_cli.py | `scripts/dev/ssot_cli.py` | ssot | no | stdlib |
| ssot_inventory.py | `scripts/dev/ssot_inventory.py` | ssot | yes | stdlib |
| ssot_registry_crosscheck.py | `scripts/dev/ssot_registry_crosscheck.py` | ssot | yes | stdlib |
| test_bloat_report.py | `scripts/dev/test_bloat_report.py` | normative | no | stdlib |
| verify_doc_claims.py | `scripts/dev/verify_doc_claims.py` | verify | no | stdlib |
| verify_doc_versions.py | `scripts/dev/verify_doc_versions.py` | verify | no | stdlib |
| verify_employee_contract.py | `scripts/dev/verify_employee_contract.py` | verify | no | stdlib |
| verify_neuro_bus_prod.py | `scripts/dev/verify_neuro_bus_prod.py` | verify | no | stdlib |
| verify_no_legacy_shims.py | `scripts/dev/verify_no_legacy_shims.py` | verify | no | stdlib |
| verify_shipment_excel_etl_closed_loop.py | `scripts/dev/verify_shipment_excel_etl_closed_loop.py` | verify | no | stdlib |
| verify_shipment_excel_etl_field_roundtrip.py | `scripts/dev/verify_shipment_excel_etl_field_roundtrip.py` | verify | no | stdlib |
| verify_surface_audit_demo_market.py | `scripts/dev/verify_surface_audit_demo_market.py` | verify | no | stdlib |
| verify_version_anchors.py | `scripts/dev/verify_version_anchors.py` | verify | yes | stdlib |
| version_sync.py | `scripts/dev/version_sync.py` | normative | yes | stdlib |
| slo_endpoint_ratchet.py | `scripts/observability/slo_endpoint_ratchet.py` | ratchet | no | stdlib |
| verify_production_slo_window.py | `scripts/observability/verify_production_slo_window.py` | verify | no | stdlib |
| verify_upgrade_rollback_evidence.py | `scripts/release/verify_upgrade_rollback_evidence.py` | verify | no | stdlib |
| verify_security_scan_pair.py | `scripts/security/verify_security_scan_pair.py` | verify | no | stdlib |
| check_openapi_consistency.py | `scripts/tools/check_openapi_consistency.py` | guard | no | stdlib |
| validate_migration.py | `scripts/validate_migration.py` | guard | no | stdlib |
| verify_arch_doc.py | `scripts/verify_arch_doc.py` | verify | no | stdlib |
| verify_contacts.py | `scripts/verify_contacts.py` | verify | no | stdlib |
| verify_mod_db_routing.py | `scripts/verify_mod_db_routing.py` | verify | no | stdlib |
| verify_sales_contract_template_env.py | `scripts/verify_sales_contract_template_env.py` | verify | no | stdlib |
| verify_six_line_event_rail.py | `scripts/verify_six_line_event_rail.py` | verify | no | stdlib |

合计：12 已纳入 ssot / 61 已登记清单 / 3 新游离
