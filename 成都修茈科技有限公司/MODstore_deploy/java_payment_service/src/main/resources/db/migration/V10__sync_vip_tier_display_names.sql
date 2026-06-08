-- 与 V6 设计一致：计划库曾停留在 V5 的「基础/专业/企业」展示名，这里强制同步为 VIP / VIP+ / SVIP1。
-- 可重复执行安全（仅 UPDATE 固定 id）。

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
