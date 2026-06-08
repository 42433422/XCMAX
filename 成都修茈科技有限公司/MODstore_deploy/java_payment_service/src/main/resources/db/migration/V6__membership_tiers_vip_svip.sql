-- 会员体系：VIP / VIP+ / SVIP1 + SVIP2~SVIP8
-- 兼容历史 plan_id 不变，避免 user_plans / orders 失效。
-- 旧 SQL 名称（可能有"基础版 MOD / 专业版 MOD / 企业版 MOD"等手工改名）一并归一。

UPDATE plan_templates
SET
  name = 'VIP',
  description = '入门会员，解锁基础 AI 调用与平台能力',
  price = 9.90,
  features_json = '["基础 AI 对话","基础模型额度","可购买更多余额","会员身份标识"]',
  quotas_json = '{"employee_count":1,"llm_calls":5000,"storage_mb":512}',
  is_active = TRUE
WHERE id = 'plan_basic';

UPDATE plan_templates
SET
  name = 'VIP+',
  description = '进阶会员，更高额度 + BYOK + 用量明细',
  price = 29.90,
  features_json = '["更高 AI 调用额度","BYOK 自有密钥","优先模型接入","用量明细","高级功能优先体验"]',
  quotas_json = '{"employee_count":3,"llm_calls":30000,"storage_mb":2048}',
  is_active = TRUE
WHERE id = 'plan_pro';

UPDATE plan_templates
SET
  name = 'SVIP1',
  description = '超级会员入门档，购买后解锁 SVIP2 ~ SVIP8',
  price = 99.90,
  features_json = '["企业级 AI 调用额度","团队/企业支持","专属部署支持","优先技术支持","解锁 SVIP2~SVIP8 购买资格"]',
  quotas_json = '{"employee_count":999999,"llm_calls":300000,"storage_mb":10240}',
  is_active = TRUE
WHERE id = 'plan_enterprise';

INSERT INTO plan_templates (id, name, description, price, features_json, quotas_json, is_active)
VALUES
  ('plan_svip2', 'SVIP2', 'SVIP 进阶档（需已是 SVIP 用户）', 199.00,  '["SVIP1 全部权益","双倍 AI 调用额度","专属客服群组","新功能内测资格"]', '{"employee_count":999999,"llm_calls":600000,"storage_mb":20480}', TRUE),
  ('plan_svip3', 'SVIP3', 'SVIP 进阶档（需已是 SVIP 用户）', 299.00,  '["SVIP2 全部权益","三倍 AI 调用额度","定制工作流模板"]', '{"employee_count":999999,"llm_calls":900000,"storage_mb":30720}', TRUE),
  ('plan_svip4', 'SVIP4', 'SVIP 进阶档（需已是 SVIP 用户）', 499.00,  '["SVIP3 全部权益","五倍 AI 调用额度","专家咨询时长 2h/月"]', '{"employee_count":999999,"llm_calls":1500000,"storage_mb":51200}', TRUE),
  ('plan_svip5', 'SVIP5', 'SVIP 进阶档（需已是 SVIP 用户）', 999.00,  '["SVIP4 全部权益","十倍 AI 调用额度","专家咨询时长 5h/月"]', '{"employee_count":999999,"llm_calls":3000000,"storage_mb":102400}', TRUE),
  ('plan_svip6', 'SVIP6', 'SVIP 进阶档（需已是 SVIP 用户）', 1999.00, '["SVIP5 全部权益","二十倍 AI 调用额度","驻场技术对接 1d/月"]', '{"employee_count":999999,"llm_calls":6000000,"storage_mb":204800}', TRUE),
  ('plan_svip7', 'SVIP7', 'SVIP 进阶档（需已是 SVIP 用户）', 2999.00, '["SVIP6 全部权益","三十倍 AI 调用额度","驻场技术对接 2d/月","品牌联合露出"]', '{"employee_count":999999,"llm_calls":9000000,"storage_mb":307200}', TRUE),
  ('plan_svip8', 'SVIP8', 'SVIP 顶级档（需已是 SVIP 用户）', 4999.00, '["SVIP7 全部权益","无限 AI 调用额度","驻场技术对接 5d/月","战略合作通道"]', '{"employee_count":999999,"llm_calls":99999999,"storage_mb":1048576}', TRUE)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  price = EXCLUDED.price,
  features_json = EXCLUDED.features_json,
  quotas_json = EXCLUDED.quotas_json,
  is_active = TRUE;
