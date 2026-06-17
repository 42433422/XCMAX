# Skill — FHD 应用层补丁

| 字段 | 值 |
|------|-----|
| 所属员工 | `fhd-core-maintainer` |

## 步骤

1. 阅读任务描述与 `FHD/docs/NEW_FEATURE_PLACEMENT.md` 落点公约。
2. 仅修改 `scope_globs` 内文件；保持 import 与分层（application / domain / infrastructure）。
3. 为变更补充或更新 `FHD/tests/` 下 pytest（优先单测，必要时 integration）。
4. 本地或 CI 等价：`cd FHD && pytest tests/ -q --maxfail=3`；覆盖率门禁由全量 `source=[app]` + `coverage_ratchet.py --check` 负责（见 `docs/reports/COVERAGE_RAMP.md`）。
5. 通过 CR 管线提交，勿直接 push main。

## 禁止

- 修改 `MODstore_deploy/modstore_server/**`（用 modstore-backend-api 员工）
- 降低 `fail_under` 或跳过测试断言
