-- 场景 2：合同到期提醒 — 月度聚合（占位）
-- 使用前：将表名/字段名替换为实际 schema；在只读 replica 上执行。
-- 参数：:evidence_month 格式 'YYYY-MM'

-- EXAMPLE — 待 DBA 确认后取消注释并调整
/*
SELECT
  date_trunc('month', scheduled_at) AS month,
  COUNT(*) AS should_push,
  COUNT(*) FILTER (WHERE push_status = 'success') AS push_success,
  COUNT(*) FILTER (WHERE push_status IN ('failed', 'skipped')) AS push_failed
FROM contract_expiry_notifications
WHERE to_char(scheduled_at, 'YYYY-MM') = :'evidence_month'
GROUP BY 1;
*/

SELECT 'placeholder: configure contract_expiry_notifications and :evidence_month' AS status;
