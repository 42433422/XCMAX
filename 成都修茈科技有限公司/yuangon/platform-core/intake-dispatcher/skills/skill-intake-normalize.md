# skill-intake-normalize

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-intake-normalize` |
| 所属员工 | `intake-dispatcher` |
| 业务域 | 自然语言/JSON/工单 → 结构化 task |
| 版本 | 1.0.0 |

## 1. 静态阶段

**输入**：`{source, raw}`。  
**执行图**：
```
1. 按 source 选解析器：
   - user_request: 直接当中文自然语言
   - customer_ticket: 解 ticket JSON 取 title+body+user_role
   - wechat: 解微信消息 JSON 取最近 5 轮上下文
   - candidate_pack: 解 .xcemp manifest 取 id/name/area
   - email: 解邮件 subject/body
2. 抽关键词 → 命中 INTENT_DICT → intent
3. 抽文件路径/glob → files_hint
4. 命中风险词典（密钥/支付/数据库/迁移/删除）→ risk_level
5. 写一行 intake_tasks(status='pending')
6. emit 'ops.intake.task.queued' 事件
```

**输出 schema**：见 README。

## 2. INTENT_DICT（部分）

| 关键词 | intent |
|--------|--------|
| 修 / 修复 / fix / bug / 报错 / 异常 | bugfix |
| 加功能 / 新增 / 接入 / 支持 | feature |
| 文档 / readme / 说明 / 同步知识 | doc |
| 部署 / 发布 / nginx / 上线 | ops |
| 数据库 / schema / 迁移 / models / alembic / 慢 SQL | dba |
| 上架 / 录用 / 面试 / xcemp | onboarding |
| 测试 / 覆盖率 / pytest / playwright | qa |

## 3. 风险词典

`high`：`secrets / .env / payment / 支付 / 余额 / 退款 / models.py / migration / drop / DELETE FROM / 私钥 / token`  
`medium`：`alembic / nginx-prod / docker-compose / deploy.sh`  
`low`：其它

## 4. 动态触发

- 静态命中 `intent=unknown` 且 `files_hint=[]` → 升级。
- 风险词典命中但 LLM 判 risk=low → 强制提至 high 并 escalate。

## 5. 固化

把 7 天内被 task-router-officer 接受率 ≥ 90% 的关键词沉淀回 `INTENT_DICT`。
