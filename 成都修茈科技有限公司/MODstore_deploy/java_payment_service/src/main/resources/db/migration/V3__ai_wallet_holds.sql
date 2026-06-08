CREATE TABLE IF NOT EXISTS wallet_holds (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id),
  hold_no VARCHAR(64) UNIQUE NOT NULL,
  amount NUMERIC(12, 2) NOT NULL,
  settled_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
  status VARCHAR(24) NOT NULL DEFAULT 'held',
  provider VARCHAR(64),
  model VARCHAR(128),
  request_id VARCHAR(128),
  idempotency_key VARCHAR(128) UNIQUE NOT NULL,
  preauth_transaction_id BIGINT,
  settlement_transaction_id BIGINT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP,
  settled_at TIMESTAMP,
  released_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_holds_user_created ON wallet_holds(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_wallet_holds_status_expires ON wallet_holds(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_wallet_holds_request_id ON wallet_holds(request_id);
