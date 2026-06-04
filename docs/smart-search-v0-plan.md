# 智能搜索 V0 计划（M3-W2 · 脚手架）

> **状态**：计划已起草；**demo 未交付**。勿在 CLAIMED 标「已验证」。

## 验收（路径图）

- 对外 API 文档（只读查询入口）
- 1 个可复现 demo（CLI 或 `/api/...`）

## 建议实现切片

1. 复用 `app/application` 产品/客户只读 facade + 现有全文检索字段
2. 单 endpoint `POST /api/search/v0`（keyword + scope）
3. 证据：`docs/evidence/smart-search-v0/demo-run-YYYYMMDD.json`

## 依赖

- 无 staging 硬依赖；与 M0 #1 独立
