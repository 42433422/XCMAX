# ESkill：自检（skill-self-check）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-self-check` |
| 所属员工 | `self-checker` |
| 业务域 | 员工包独立可执行自检 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
_build_employee_pack_zip_with_source(employee_pack)
→ 构建 .xcemp 包
→ 子进程 python xxx.xcemp validate
→ 自检结果
→ 若失败：自动修复 → 重试 python xxx.xcemp validate（最多 2 次）
→ 输出自检结果
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "xcemp_path": "",
  "load_result": { "status": "", "errors": [] },
  "skill_init_results": [
    { "skill_id": "", "status": "", "errors": [] }
  ],
  "repair_attempts": [
    { "attempt": 0, "action": "", "result": "" }
  ],
  "summary": ""
}
```

**工具绑定**：
- _build_employee_pack_zip_with_source
- python xxx.xcemp validate（子进程）

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 子进程执行异常退出 |
| 结果不达标 | load_result.status == "fail" 或任意 skill_init_results.status == "fail" |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析自检失败原因 → 判断是加载错误还是 skill 初始化缺陷 → 生成修复补丁 → 重新构建 .xcemp 包并重试。

**允许改动的模块白名单**：
- workbench/selfcheck/* 配置文件

## 4. 固化

**验收标准**：
- [ ] load_result.status == "ok"
- [ ] 所有 skill_init_results.status == "ok"
- [ ] repair_attempts 为空或最后一次 attempt result == "ok"
