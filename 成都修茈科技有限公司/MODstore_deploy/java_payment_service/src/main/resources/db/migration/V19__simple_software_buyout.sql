-- New sales use one permanent software license. Keep historical templates,
-- user_plans, entitlements and immutable order amounts for existing customers.
INSERT INTO plan_templates (id, name, description, price, features_json, quotas_json, is_active)
VALUES ('saas-permanent-standard', 'XCAGI 软件买断',
        '6,800 元一次购买，永久使用已购软件；定制按确认的报价收费，AI 调用按量另计。',
        6800.00, '["软件永久使用","无软件续租费","定制另行报价","AI 调用按量付费"]', '{}', TRUE)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, description = EXCLUDED.description, price = EXCLUDED.price,
    features_json = EXCLUDED.features_json, quotas_json = EXCLUDED.quotas_json,
    is_active = EXCLUDED.is_active;
