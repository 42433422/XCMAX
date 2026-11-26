-- New-sales template only. Preserve pending/paid orders, user plans,
-- entitlements, wallets and the already applied V19 migration.
UPDATE plan_templates
SET price = 3000.00,
    description = '3,000 元一次购买，永久使用已购软件；定制按确认的报价收费，AI 调用按量另计。'
WHERE id = 'saas-permanent-standard';
