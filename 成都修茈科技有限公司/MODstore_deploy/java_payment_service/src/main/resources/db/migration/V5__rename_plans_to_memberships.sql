UPDATE plan_templates
SET
  name = '基础会员',
  description = '适合轻量使用，包含基础 AI 调用额度与平台能力',
  features_json = '["基础 AI 对话","基础模型额度","可购买更多余额","会员身份标识"]'
WHERE id = 'plan_basic';

UPDATE plan_templates
SET
  name = '专业会员',
  description = '适合高频使用，包含更高额度与 BYOK 能力',
  features_json = '["更高 AI 调用额度","BYOK 自有密钥","优先模型接入","用量明细","高级功能优先体验"]'
WHERE id = 'plan_pro';

UPDATE plan_templates
SET
  name = '企业会员',
  description = '适合团队与商业运营，包含企业级额度和部署支持',
  features_json = '["企业级 AI 调用额度","团队/企业支持","专属部署支持","优先技术支持","自定义域名"]'
WHERE id = 'plan_enterprise';
