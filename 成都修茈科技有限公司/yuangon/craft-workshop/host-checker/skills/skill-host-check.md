# ESkill：宿主环境检查（skill-host-check）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-host-check` |
| 所属员工 | `host-checker` |
| 业务域 | 宿主环境连通性探测 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
get_external_client().get("/api/mods/")
→ 员工管理服务可达性结果
→ get_external_client().get("/api/mods/llm-status")
→ LLM 密钥状态结果
→ get_external_client().get("/api/version")
→ API 版本兼容性结果
→ 输出连通性报告
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "endpoints": [
    {
      "path": "/api/mods/",
      "status": "",
      "response_time_ms": 0,
      "error": ""
    },
    {
      "path": "/api/mods/llm-status",
      "status": "",
      "llm_keys": [
        { "provider": "", "status": "", "quota_remaining": 0 }
      ],
      "response_time_ms": 0,
      "error": ""
    },
    {
      "path": "/api/version",
      "status": "",
      "client_version": "",
      "server_version": "",
      "compatible": true,
      "response_time_ms": 0,
      "error": ""
    }
  ],
  "summary": ""
}
```

**工具绑定**：
- get_external_client().get()

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 任意端点请求抛出异常或超时 |
| 结果不达标 | 任意端点 status != "ok" 或 compatible == false |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析连通性失败原因 → 判断是网络问题、密钥过期还是版本不兼容 → 生成诊断建议与修复步骤。

**允许改动的模块白名单**：
- workbench/hostcheck/* 配置文件

## 4. 固化

**验收标准**：
- [ ] 所有端点 status == "ok"
- [ ] 所有 LLM 密钥 status == "valid"
- [ ] API 版本 compatible == true
