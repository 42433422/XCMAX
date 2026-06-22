# `*_v2` 应用服务收敛结果

> **状态（2026-06）**：应用层 `*_app_service_v2.py` 已删除。HTTP、planner、tooling 统一使用无后缀 application service 或领域/路由登记模块；不再维护 V1/V2 双轨登记表。

## 1. 结论

- `FHD/app/application/*_app_service_v2.py`：0 个。
- `app/application/app_service_pair_registry.py`：已删除，不再用 registry 为双轨制背书。
- `scripts/ci/v2_versioned_py_allowlist.txt`：不再允许 application service 例外；仅保留协议名本身带版本的兼容层。
- 新增架构测试：`tests/test_application/test_no_app_service_v2_files.py`，防止应用层 `_v2` 文件回潮。

## 2. 后续规则

- 新应用服务使用无后缀模块名，例如 `foo_app_service.py`。
- 既有业务能力优先合并进现有无后缀 application service、`app/fastapi_routes/domains/` 或明确的 domain 登记模块。
- 禁止用 `*_v3.py`、`*_v4.py` 等新后缀继续分叉。
- 若确实需要外部协议兼容层，必须不是 application service，并需要加入 allowlist 与说明。

## 3. 本地检查

```bash
find FHD/app/application -name "*_app_service_v2.py"
python scripts/guard_no_new_v2_files.py FHD/app/application/new_foo_app_service_v2.py
```

期望：

- 第一条无输出。
- 第二条退出码为 1。
