-- svip（plan_enterprise）副标题与权益仅介绍本档，不提及其他档位或「解锁」进阶线
-- 注：版本号从 9 改为 12 以避免与 V9__orders_dismissed_by_user.sql 撞版本（Flyway 启动校验报 "more than one migration with version 9"）
UPDATE plan_templates
SET
  name = 'svip',
  description = '企业级会员（svip），含大额度企业 AI 调用、团队/部署与优先支持',
  features_json = '["企业级 AI 调用额度","团队/企业支持","专属部署支持","优先技术支持"]'
WHERE id = 'plan_enterprise';
