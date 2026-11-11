# FHD 测试入口

## 统一 pytest 入口

从 `FHD/` 执行 `python -m pytest tests/`，使用 [`../pyproject.toml`](../pyproject.toml) 和 [`conftest.py`](conftest.py)，与 CI 一致。
从仓库根执行 `make test`；`make test-xcagi` 是同一入口的兼容别名。

单域或单文件可在 `FHD/` 指定路径，例如 `python -m pytest tests/test_dev/test_ssot_registry_crosscheck.py -q`。

## 共享 fixture

- App 工厂：[`fixtures/app_factory.py`](fixtures/app_factory.py) · `get_test_fastapi_app()`
- 路由子目录：[`routes/conftest.py`](routes/conftest.py)

## 测试选择与覆盖率

默认收集完整 `tests/`。`conftest.py` 给 `test_coverage_ramp_*.py` 添加 `coverage_ramp` 标记；仅检查行为套件时可用 `python -m pytest tests/ -m 'not coverage_ramp'`。

覆盖率门槛见 [`../docs/reports/COVERAGE_RAMP.md`](../docs/reports/COVERAGE_RAMP.md)。

## ELT intake sample pack

Synthetic MIMO/丢文件 fixtures: [`../testdata/elt-intake-samples/`](../testdata/elt-intake-samples/README.md).
