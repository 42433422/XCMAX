# ESkill：发布流水线执行（skill-deploy-pipeline）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-deploy-pipeline` |
| 所属员工 | `deploy-release-officer` |
| 业务域 | 构建与发布编排 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
Pre-flight 检查（测试/密钥/配置）→ 构建（npm build / docker build）
→ 上传/部署（腾讯云 Pages / docker push）→ 冒烟验证 → 输出报告
```

**输出 schema**：
```json
{ "status": "ok | error", "build_ok": true, "deploy_ok": true, "smoke_ok": true, "rollback_needed": false }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | build 或 deploy 命令返回非零 |
| 结果不达标 | `smoke_ok == false` |

## 3. 动态阶段

**预算**：4000 tokens，5 步。  
**不允许**：自动修改业务源码；生产回滚需人工确认。

## 4. 固化

**验收标准**：`build_ok && deploy_ok && smoke_ok == true`，且无新增告警。
