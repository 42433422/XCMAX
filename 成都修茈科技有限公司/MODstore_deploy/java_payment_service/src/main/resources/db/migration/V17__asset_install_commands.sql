CREATE TABLE IF NOT EXISTS asset_install_commands (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    purchase_id BIGINT NOT NULL REFERENCES purchases(id),
    catalog_id BIGINT NOT NULL REFERENCES catalog_items(id),
    installation_id VARCHAR(64) NOT NULL DEFAULT '*',
    idempotency_key VARCHAR(192) NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'user_click',
    source_event_id VARCHAR(192) NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    claimed_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_asset_install_command_idempotency UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_asset_install_commands_user_id ON asset_install_commands(user_id);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_purchase_id ON asset_install_commands(purchase_id);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_catalog_id ON asset_install_commands(catalog_id);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_installation_id ON asset_install_commands(installation_id);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_idempotency_key ON asset_install_commands(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_source ON asset_install_commands(source);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_source_event_id ON asset_install_commands(source_event_id);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_status ON asset_install_commands(status);
CREATE INDEX IF NOT EXISTS ix_asset_install_commands_created_at ON asset_install_commands(created_at);
