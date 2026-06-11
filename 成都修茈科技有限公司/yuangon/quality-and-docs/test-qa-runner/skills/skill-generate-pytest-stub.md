# Skill — 为 diff 文件生成 pytest 骨架

| 字段 | 值 |
|------|-----|
| 所属员工 | `test-qa-runner` |

## 步骤

1. 从 CR 或任务描述识别变更的 `FHD/app/**` 模块。
2. 在 `FHD/tests/` 下创建或扩展 `test_<module>.py`，至少包含一个可运行用例（mock 外部 IO）。
3. 不降低 `fail_under`；不删除现有断言。
4. 提交到 `employees/test-qa-runner/` 分支并打 `auto-merge` 标签。

## 示例模式

```python
def test_service_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
```
