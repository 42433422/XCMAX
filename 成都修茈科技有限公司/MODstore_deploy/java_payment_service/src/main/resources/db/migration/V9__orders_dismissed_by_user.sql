-- 用户一键「从列表中隐藏」非进行中的订单（不删库，仅隐藏）
ALTER TABLE orders ADD COLUMN IF NOT EXISTS dismissed_by_user BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_orders_user_dismissed ON orders (user_id, dismissed_by_user);
