# 1.0-A 通用首样板 · 自动化证据（2026-07-29）

## 决策

首样板行业锁定为 **通用**。清单：[`../../customer/ACCEPTANCE_GENERIC_1.0-A.md`](../../customer/ACCEPTANCE_GENERIC_1.0-A.md)。

## 自动化（本机）

```text
uv run python -m pytest \
  tests/test_deliverable_status.py \
  tests/test_edition_policy.py \
  tests/test_industry_baseline.py::test_industry_baseline_generic_minimal \
  -q
→ 19 passed（2026-07-29）
```

## 待补（人工 / 安装包）

- [ ] 引导选「通用」截图
- [ ] 三动作截图（对话 / capabilities / neuro-bus）
- [ ] `deliverable-status` JSON 落盘
- [ ] enterprise 安装包冷启（Win 优先）
