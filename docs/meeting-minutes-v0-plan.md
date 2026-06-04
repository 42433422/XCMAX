# 智能纪要 V0 计划（M3-W3 · 脚手架）

> **状态**：计划已起草；**demo 未交付**。需第三方 API Key（通义听悟 / 腾讯会议），勿提交密钥。

## 验收（路径图）

- 选定 1 家纪要 SaaS SDK
- 1 个 demo：音频/会议链接 → 结构化纪要 JSON

## 建议实现切片

1. `app/infrastructure/gateways/meeting_minutes.py` 抽象
2. CLI `scripts/meeting_minutes_v0/run_demo.py` + `docs/evidence/meeting-minutes-v0/`

## 依赖

- 商务/API 合同；与 M0 staging 独立
