ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR(32);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refunded_amount NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_status VARCHAR(32) NOT NULL DEFAULT 'none';
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMP;

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS balance_before NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS balance_after NUMERIC(12, 2) NOT NULL DEFAULT 0;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS order_no VARCHAR(64);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS refund_no VARCHAR(64);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128);

CREATE UNIQUE INDEX IF NOT EXISTS uk_transactions_idempotency_key
  ON transactions(idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_transactions_order_no ON transactions(order_no);
CREATE INDEX IF NOT EXISTS idx_transactions_refund_no ON transactions(refund_no);

CREATE TABLE IF NOT EXISTS refunds (
  id BIGSERIAL PRIMARY KEY,
  refund_no VARCHAR(64) UNIQUE NOT NULL,
  order_id BIGINT NOT NULL REFERENCES orders(id),
  user_id BIGINT NOT NULL REFERENCES users(id),
  amount NUMERIC(12, 2) NOT NULL,
  reason TEXT NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  admin_note TEXT,
  reviewed_by BIGINT REFERENCES users(id),
  wallet_transaction_id BIGINT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  reviewed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_refunds_user_created ON refunds(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_refunds_order ON refunds(order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_status ON refunds(status);

CREATE TABLE IF NOT EXISTS plan_templates (
  id VARCHAR(64) PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  description TEXT,
  price NUMERIC(12, 2) NOT NULL DEFAULT 0,
  features_json TEXT DEFAULT '[]',
  quotas_json TEXT DEFAULT '{}',
  is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS entitlements (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  catalog_id BIGINT,
  entitlement_type VARCHAR(32) NOT NULL,
  source_order_id VARCHAR(64) UNIQUE NOT NULL,
  metadata_json TEXT DEFAULT '{}',
  is_active BOOLEAN NOT NULL DEFAULT true,
  granted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_plans (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  plan_id VARCHAR(64) NOT NULL REFERENCES plan_templates(id),
  source_order_id VARCHAR(64),
  started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS quotas (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  quota_type VARCHAR(64) NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  used INTEGER NOT NULL DEFAULT 0,
  reset_at TIMESTAMP,
  CONSTRAINT uk_quotas_user_type UNIQUE (user_id, quota_type)
);

ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;
ALTER TABLE user_plans ADD COLUMN IF NOT EXISTS source_order_id VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_entitlements_user_active ON entitlements(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_entitlements_source_order ON entitlements(source_order_id);
CREATE INDEX IF NOT EXISTS idx_user_plans_user_active ON user_plans(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_user_plans_source_order ON user_plans(source_order_id);
