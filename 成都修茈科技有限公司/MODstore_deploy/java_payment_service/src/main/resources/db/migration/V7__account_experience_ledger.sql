-- 与 JPA 实体 AccountExperienceLedger 对齐（此前仅有实体无迁移，validate 会失败）

CREATE TABLE IF NOT EXISTS account_experience_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users (id),
    source_type VARCHAR(32) NOT NULL,
    source_order_id VARCHAR(64) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    xp_delta BIGINT NOT NULL,
    description TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_account_xp_source UNIQUE (source_type, source_order_id)
);

CREATE INDEX IF NOT EXISTS idx_account_xp_user ON account_experience_ledger (user_id);
