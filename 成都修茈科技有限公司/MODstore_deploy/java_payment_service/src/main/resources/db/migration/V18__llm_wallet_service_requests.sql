ALTER TABLE wallet_holds ADD COLUMN IF NOT EXISTS billing_source VARCHAR(16) NOT NULL DEFAULT 'legacy';

CREATE TABLE llm_wallet_service_requests (
    operation_key VARCHAR(192) PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    operation VARCHAR(16) NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    hold_no VARCHAR(64) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE llm_wallet_service_nonces (
    nonce VARCHAR(32) PRIMARY KEY,
    operation_key VARCHAR(192) NOT NULL REFERENCES llm_wallet_service_requests(operation_key),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
