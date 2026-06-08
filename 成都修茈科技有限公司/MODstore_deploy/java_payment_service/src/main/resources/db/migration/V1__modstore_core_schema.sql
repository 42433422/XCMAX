CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  email VARCHAR(128) UNIQUE,
  password_hash VARCHAR(256) NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE,
  default_llm_json TEXT DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallets (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL UNIQUE REFERENCES users(id),
  balance NUMERIC(12, 2) NOT NULL DEFAULT 0,
  version BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  amount NUMERIC(12, 2) NOT NULL,
  txn_type VARCHAR(32) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'completed',
  description TEXT DEFAULT '',
  reference_no VARCHAR(64),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);

CREATE TABLE IF NOT EXISTS catalog_items (
  id BIGSERIAL PRIMARY KEY,
  pkg_id VARCHAR(128) NOT NULL UNIQUE,
  version VARCHAR(32) NOT NULL DEFAULT '',
  name VARCHAR(256) NOT NULL,
  description TEXT DEFAULT '',
  price NUMERIC(12, 2) NOT NULL DEFAULT 0,
  author_id BIGINT REFERENCES users(id),
  artifact VARCHAR(32) DEFAULT 'mod',
  industry VARCHAR(64) DEFAULT '通用',
  stored_filename VARCHAR(256) DEFAULT '',
  sha256 VARCHAR(64) DEFAULT '',
  is_public BOOLEAN DEFAULT TRUE,
  security_level VARCHAR(32) DEFAULT 'personal',
  industry_code VARCHAR(16) DEFAULT '',
  industry_secondary VARCHAR(64) DEFAULT '',
  description_embedding TEXT DEFAULT '',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_catalog_items_pkg_id ON catalog_items(pkg_id);

CREATE TABLE IF NOT EXISTS purchases (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  catalog_id BIGINT NOT NULL REFERENCES catalog_items(id),
  amount NUMERIC(12, 2) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_purchases_user_id ON purchases(user_id);

CREATE TABLE IF NOT EXISTS plan_templates (
  id VARCHAR(64) PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  description TEXT DEFAULT '',
  price NUMERIC(12, 2) NOT NULL DEFAULT 0,
  features_json TEXT DEFAULT '[]',
  quotas_json TEXT DEFAULT '{}',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_plans (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  plan_id VARCHAR(64) NOT NULL REFERENCES plan_templates(id),
  started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_user_plans_user_id ON user_plans(user_id);
CREATE INDEX IF NOT EXISTS idx_user_plans_plan_id ON user_plans(plan_id);
CREATE INDEX IF NOT EXISTS idx_user_plans_active ON user_plans(is_active);

CREATE TABLE IF NOT EXISTS quotas (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  quota_type VARCHAR(64) NOT NULL,
  total INTEGER NOT NULL DEFAULT 0,
  used INTEGER NOT NULL DEFAULT 0,
  reset_at TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_user_quota_type UNIQUE (user_id, quota_type)
);

CREATE INDEX IF NOT EXISTS idx_quotas_user_id ON quotas(user_id);
CREATE INDEX IF NOT EXISTS idx_quotas_quota_type ON quotas(quota_type);

CREATE TABLE IF NOT EXISTS entitlements (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  catalog_id BIGINT REFERENCES catalog_items(id),
  entitlement_type VARCHAR(32) NOT NULL,
  source_order_id VARCHAR(64) DEFAULT '',
  metadata_json TEXT DEFAULT '{}',
  granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  is_active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_entitlements_user_id ON entitlements(user_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_catalog_id ON entitlements(catalog_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_type ON entitlements(entitlement_type);
CREATE INDEX IF NOT EXISTS idx_entitlements_source_order ON entitlements(source_order_id);
CREATE INDEX IF NOT EXISTS idx_entitlements_active ON entitlements(is_active);

CREATE TABLE IF NOT EXISTS refund_requests (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  order_no VARCHAR(64) NOT NULL,
  amount NUMERIC(12, 2) NOT NULL,
  reason TEXT NOT NULL,
  status VARCHAR(16) DEFAULT 'pending',
  admin_note TEXT DEFAULT '',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_refund_requests_user_id ON refund_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_refund_requests_order_no ON refund_requests(order_no);
CREATE INDEX IF NOT EXISTS idx_refund_requests_status ON refund_requests(status);

CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY,
  out_trade_no VARCHAR(64) NOT NULL UNIQUE,
  trade_no VARCHAR(64),
  user_id BIGINT NOT NULL REFERENCES users(id),
  subject VARCHAR(256) NOT NULL,
  total_amount NUMERIC(12, 2) NOT NULL,
  order_kind VARCHAR(32) NOT NULL,
  item_id BIGINT,
  plan_id VARCHAR(64),
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  buyer_id VARCHAR(64),
  paid_at TIMESTAMP,
  fulfilled BOOLEAN NOT NULL DEFAULT FALSE,
  qr_code TEXT,
  pay_type VARCHAR(32),
  request_id VARCHAR(64) UNIQUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_orders_user_created ON orders(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_trade_no ON orders(trade_no);

INSERT INTO plan_templates (id, name, description, price, features_json, quotas_json, is_active)
VALUES
  ('plan_basic', '基础会员', '适合轻量使用，包含基础 AI 调用额度与平台能力', 9.90, '["基础 AI 对话","基础模型额度","可购买更多余额","会员身份标识"]', '{"employee_count":1,"llm_calls":5000,"storage_mb":512}', TRUE),
  ('plan_pro', '专业会员', '适合高频使用，包含更高额度与 BYOK 能力', 29.90, '["更高 AI 调用额度","BYOK 自有密钥","优先模型接入","用量明细","高级功能优先体验"]', '{"employee_count":3,"llm_calls":30000,"storage_mb":2048}', TRUE),
  ('plan_enterprise', '企业会员', '适合团队与商业运营，包含企业级额度和部署支持', 99.90, '["企业级 AI 调用额度","团队/企业支持","专属部署支持","优先技术支持","自定义域名"]', '{"employee_count":999999,"llm_calls":300000,"storage_mb":10240}', TRUE)
ON CONFLICT (id) DO NOTHING;
