-- 与 JPA 实体 User.experience 对齐（V1 建表时未包含）

ALTER TABLE users ADD COLUMN IF NOT EXISTS experience BIGINT NOT NULL DEFAULT 0;
