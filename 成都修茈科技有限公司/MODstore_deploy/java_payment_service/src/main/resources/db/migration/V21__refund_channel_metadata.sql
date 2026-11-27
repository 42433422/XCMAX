ALTER TABLE refunds
    ADD COLUMN IF NOT EXISTS refund_channel VARCHAR(32) NOT NULL DEFAULT 'wallet';

ALTER TABLE refunds
    ADD COLUMN IF NOT EXISTS channel_refund_no VARCHAR(128);

ALTER TABLE refunds
    ADD COLUMN IF NOT EXISTS channel_refund_status VARCHAR(32);
