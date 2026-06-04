-- 场景 1：发货单自动审 — 月度聚合（占位）
-- 使用前：将表名/字段名替换为实际 schema；在只读 replica 上执行。
-- 参数：:evidence_month 格式 'YYYY-MM'

-- EXAMPLE — 待 DBA 确认后取消注释并调整
/*
SELECT
  date_trunc('month', created_at) AS month,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE decision = 'auto_approve') AS auto_approve,
  COUNT(*) FILTER (WHERE decision = 'manual') AS manual,
  COUNT(*) FILTER (WHERE decision = 'ocr_failed') AS ocr_failed
FROM shipment_audit_events
WHERE to_char(created_at, 'YYYY-MM') = :'evidence_month'
GROUP BY 1;
*/

SELECT 'placeholder: configure shipment_audit_events and :evidence_month' AS status;
