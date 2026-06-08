# Postmortem：全量 pytest 测试污染与 xpassed 收口（2026-06）

## 摘要

| 字段 | 内容 |
|------|------|
| 严重级别 | SEV-3（质量门禁不可信） |
| 持续时长 | 多迭代（Phase 0–v10） |
| 错误预算 | 工程效能 SLO（发布信心） |

## 影响

- 全量套件出现 **1109+ xpassed**（`pytestmark = xfail(strict=False)` 临时标记）。
- 尽调视角：CI 看似「大量通过」，实际为预期失败被掩盖。
- `xfail_strict=true` 后须清零 xpassed，否则门禁应失败。

## 根因

1. **Class-level 状态污染**（如 `RedisCache.is_available` 被 `type(cache).is_available = property(...)` 修改未还原）。
2. **隔离跑过、全量失败** 的 coverage_ramp 文件被模块级 xfail 临时兜底。
3. **`phase59_inventory`** 等在 import 阶段注入假 `sys.modules['app']`，破坏后续 SQLAlchemy 导入。

## 修复

- 移除全部模块级 `xfail`；污染用例改 fixture teardown / `monkeypatch`。
- `tests/conftest.py`：默认 `DATABASE_URL=sqlite://`；`reset_fastapi_app_singleton()`。
- `phase59`：延迟加载 + 禁止覆盖真实 `app` 包。
- `wechat_message_source_size_payload` 改从 `wechat_contact_cache_import` 导出。

## 行动项

| 项 | 状态 |
|----|------|
| 全量 `0 xpassed` 验收 | 已达成（2026-06-04 复跑） |
| `pytest-random-order` 升为 required（全绿后） | 待 backend-test 全绿 |
| PHASE0 §7.2「xpassed 是成果」勘误 | 见 `PHASE0_BASELINE.md` 修订说明 |

## 错误预算

- 消耗：内部 QA 迭代时间 ~2 人周（已计入 v10 技术债清偿）。
