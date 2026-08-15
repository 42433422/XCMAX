ALTER TABLE users
  ADD COLUMN IF NOT EXISTS is_enterprise BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS account_state VARCHAR(32) NOT NULL DEFAULT 'pending_plan';

CREATE INDEX IF NOT EXISTS idx_users_account_state ON users(account_state);

UPDATE users
SET account_state = 'active'
WHERE is_admin = TRUE OR is_enterprise = TRUE;
