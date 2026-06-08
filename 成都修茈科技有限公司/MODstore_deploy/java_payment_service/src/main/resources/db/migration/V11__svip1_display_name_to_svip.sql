-- plan_enterprise 展示名由 "SVIP1" 统一为 "svip"（用户可见）；plan_id 仍为 plan_enterprise
UPDATE plan_templates
SET name = 'svip'
WHERE id = 'plan_enterprise' AND (name = 'SVIP1' OR name = '企业会员');

-- SVIP2 权益首条与入门档名称一致
UPDATE plan_templates
SET features_json = replace(features_json, 'SVIP1 全部权益', 'svip 全部权益')
WHERE id = 'plan_svip2' AND strpos(coalesce(features_json, ''), 'SVIP1 全部权益') > 0;
