ALTER TABLE users
  ADD COLUMN IF NOT EXISTS enterprise_subject_id VARCHAR(128);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS enterprise_legal_name VARCHAR(256);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS enterprise_verification_sha256 VARCHAR(64);

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS enterprise_verified_at TIMESTAMP;

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS enterprise_verified_by_user_id BIGINT;

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS enterprise_subject_id VARCHAR(128);

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS enterprise_legal_name VARCHAR(256);

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS enterprise_verification_sha256 VARCHAR(64);

ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS enterprise_verified_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_orders_enterprise_subject
  ON orders(enterprise_subject_id)
  WHERE enterprise_subject_id IS NOT NULL;
