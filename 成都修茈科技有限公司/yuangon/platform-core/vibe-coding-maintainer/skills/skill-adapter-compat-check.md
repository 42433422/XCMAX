# ESkill：适配器兼容性检查（skill-adapter-compat-check）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-adapter-compat-check` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | vibe-coding 与 MODstore vibe_adapter 接口兼容性维护 |
| 版本 | 1.0.0 |

---

## 1. 静态阶段

**触发条件**：`facade.py` 公开 API 签名变更，或定时巡检触发。

**执行逻辑**：

```
提取 facade.py 的 VibeCoder 类全部公开方法签名（名称 + 参数 + 返回类型）
→ 扫描 MODstore_deploy/modstore_server/integrations/vibe_adapter.py 中对 VibeCoder 的所有调用点
→ 对比：参数数量、参数名、参数类型、返回值使用方式
→ 扫描 MODstore_deploy/modstore_server/eskill_runtime.py 中 VibeESkillAdapter 的调用点
→ 扫描 MODstore_deploy/modstore_server/workflow_engine.py 中 vibe_skill / vibe_workflow 节点的调用点
→ 输出兼容性报告
```

**输出 schema**：
```json
{
  "status": "ok | error",
  "facade_methods_total": 0,
  "adapter_call_sites": 0,
  "breaking_changes": [],
  "warnings": [],
  "details": [
    {
      "method": "VibeCoder.code",
      "adapter_file": "vibe_adapter.py",
      "issue": "缺少新增的 mode 参数默认值"
    }
  ]
}
```

**工具绑定**：
- `python -c "import ast; ..."` — 提取 facade.py 方法签名
- `grep` — 扫描 vibe_adapter.py / eskill_runtime.py / workflow_engine.py 调用点
- `python -m pytest tests/test_vibe_adapter.py` — 适配器测试（如有）

---

## 2. 动态触发条件

| 触发类型 | 具体规则 | 阈值 |
|----------|----------|------|
| 结果不达标 | `breaking_changes` 非空 | 即触发 |
| 代码变更 | `facade.py` 的 VibeCoder 类方法签名变更 | 即触发 |

---

## 3. 动态自适应阶段

**预算限制**：
- 最大 token：4000
- 最大步数：5

**允许改动的模块白名单**：
- `vibe-coding/src/vibe_coding/facade.py`（仅允许添加默认参数值，不删除已有参数）
- `vibe-coding/tests/test_facade.py`

**LLM 任务**：分析 breaking_changes → 为新增参数添加默认值以保持向后兼容 → 更新 facade.py → 通知 `employee-pack-curator` 评估影响。

**注意**：如果兼容性无法通过默认参数修复，则**不自动修改**，而是升级为人工处理（`escalate_to_human: true`）。

---

## 4. 固化

**验收标准**：
- `breaking_changes` 为空
- `facade.py` 所有公开方法保持向后兼容
- `vibe_adapter.py` 所有调用点正常工作
- `employee-pack-curator` 已收到兼容性变更通知

---

## 5. 评估指标

| 指标 | 目标值 |
|------|--------|
| 接口向后兼容率 | 100% |
| breaking_changes 检出率 | 100% |
| 静态路径成功率 | ≥ 95% |
| 平均延迟 | < 10s（静态扫描） |
