# FHD 测试入口

## 两套 pytest 根 conftest

| 套件 | 命令 | conftest |
|------|------|----------|
| **CI 默认** | `pytest tests/` 或 `make test` | [`conftest.py`](conftest.py) |
| **XCAGI 遗留** | `pytest XCAGI/xcagi_tests --import-mode=importlib` 或 `make test-xcagi` | [`XCAGI/xcagi_tests/conftest.py`](../XCAGI/xcagi_tests/conftest.py) |

**勿同时收集** `tests/` 与 `XCAGI/xcagi_tests`（模块名冲突，见 `pyproject.toml`）。

## 决策树

```
需要整机 FastAPI + TestClient？
├─ 是，且走 CI 默认门禁 → pytest tests/
├─ 是，且要 XCAGI 子树历史用例 → pytest XCAGI/xcagi_tests --import-mode=importlib
└─ 仅单域/单文件 → pytest tests/routes/test_health.py -q
```

## 共享 fixture

- App 工厂：[`fixtures/app_factory.py`](fixtures/app_factory.py) · `get_test_fastapi_app()`
- 路由子目录：[`routes/conftest.py`](routes/conftest.py)

## CI 稳定子集

`CI_STABLE_ONLY=1 pytest tests/` 仅跑白名单 nodeid（见 `conftest.py` `_CI_STABLE_NODEID_FRAGMENTS`）。

## collect_ignore

遗留/未落地用例暂从采集排除；收尾见 [`docs/reports/COVERAGE_RAMP.md`](docs/reports/COVERAGE_RAMP.md) ④-B。
