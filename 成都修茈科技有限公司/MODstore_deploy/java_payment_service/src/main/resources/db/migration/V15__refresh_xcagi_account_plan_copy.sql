-- Refresh customer-facing XCAGI plan copy without changing IDs, prices, or entitlements.
INSERT INTO plan_templates (id, name, description, price, features_json, quotas_json, is_active)
VALUES
  ('saas-trial-30', '30 天全功能体验', '用 30 天完整体验 XCAGI，包含 100 元 AI 使用额度。', 99.00, '["XCAGI 桌面端完整功能","30 天使用期","100 元 AI 使用额度"]', '{}', TRUE),
  ('saas-permanent-starter', '企业启航版', '适合首次部署 XCAGI 的企业，包含 1 个行业 Mod、四部门 AI 员工配置、上线交付与 1 年维护。', 49999.00, '["永久使用 XCAGI","1 个行业 Mod","四部门 AI 员工配置","1 年维护"]', '{}', TRUE),
  ('saas-permanent-growth', '企业成长版', '适合需要多业务协同或现有系统对接的企业，包含专属 AI 员工训练与 2 年维护。', 99999.00, '["永久使用 XCAGI","多行业 Mod 组合","现有系统对接","专属 AI 员工训练","2 年维护"]', '{}', TRUE),
  ('saas-permanent-max', '集团协同版', '适合多组织、多分支机构协同的集团企业，包含集团架构支持与 3 年维护。', 499999.00, '["永久使用 XCAGI","集团多组织架构","多分支协同","3 年维护"]', '{}', TRUE),
  ('saas-permanent-ultra', '企业旗舰版', '适合需要深度定制与长期技术保障的企业，包含源码托管、二次开发授权与 99.9% SLA。', 999999.00, '["永久使用 XCAGI","源码托管","二次开发授权","99.9% SLA"]', '{}', TRUE)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  price = EXCLUDED.price,
  features_json = EXCLUDED.features_json,
  quotas_json = EXCLUDED.quotas_json,
  is_active = TRUE;
