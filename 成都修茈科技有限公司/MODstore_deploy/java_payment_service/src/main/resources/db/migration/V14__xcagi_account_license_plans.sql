-- XCAGI account licenses are separate from VIP/SVIP usage memberships.
INSERT INTO plan_templates (id, name, description, price, features_json, quotas_json, is_active)
VALUES
  ('saas-trial-30', '30 天试用', '99 元体验账户，含 100 元额度，30 天到期后冻结，可购买永久授权继续使用。', 99.00, '["XCAGI 桌面端账号授权","30 天全功能体验","含 100 元 AI 额度"]', '{}', TRUE),
  ('saas-permanent-starter', '永久授权 · 1–5 万', '1 个行业 Mod 定制 + 四部门 AI 员工配置 + 1-3 天上线交付 + 1 年免费维护。', 49999.00, '["XCAGI 永久账号授权","1 个行业 Mod 定制","1 年免费维护"]', '{}', TRUE),
  ('saas-permanent-growth', '永久授权 · 5–10 万', '多行业 Mod 组合 + 现有系统对接 + 专属 AI 员工训练 + 2 年免费维护。', 99999.00, '["XCAGI 永久账号授权","多行业 Mod 与系统对接","2 年免费维护"]', '{}', TRUE),
  ('saas-permanent-max', '永久授权 · 10–50 万', '集团多组织架构 + 3 年免费维护，一次购买永久使用。', 499999.00, '["XCAGI 永久账号授权","集团多组织架构","3 年免费维护"]', '{}', TRUE),
  ('saas-permanent-ultra', '永久授权 · 50–100 万', '源码托管 + 二开授权 + SLA 99.9% 保障，一次购买永久使用。', 999999.00, '["XCAGI 永久账号授权","源码托管与二开授权","SLA 99.9% 保障"]', '{}', TRUE)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  price = EXCLUDED.price,
  features_json = EXCLUDED.features_json,
  quotas_json = EXCLUDED.quotas_json,
  is_active = TRUE;
