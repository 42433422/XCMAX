# AIOPEN 审计身份候选修复 — 2026-10-28

## 改动

管理操作的审计操作者由 require_admin_user 返回的服务端认证身份传入。工具调用、MCP 和 AIOPEN/Qclaw OpenClaw 代理不再使用 body/args 的 user_id 或 userId 指定审计操作者。未绑定个人身份的 API Key 使用明确的 aiopen-api-key 服务主体，不能据此声称识别了某个自然人。

## 验证

在保留的 CI 源码制品上核对 ai_open.py 和 ai_qclaw.py 与基线 c9bfdab8764b22fbfb9a4202dd368d74afe621ea 的 Git blob 完全一致后应用候选修改。Python 3.13 本地执行：

```sh
cd FHD
python -m pytest -q tests/test_security/test_aiopen_audit_identity.py -o addopts=''
```

结果：14 passed。包含辅助函数伪造字段、已认证管理员路由、REST/MCP 工具调用及两个兼容代理入口。未执行全仓回归或生产验收。

## 依赖和边界

本分支堆叠在 #2717 的 c9bfdab8764b22fbfb9a4202dd368d74afe621ea 之上；不覆盖其未合入状态。现有鉴权、响应契约和历史审计记录不改。跨租户目标授权、Key-to-tenant 绑定、Qclaw 原文追踪及外部凭据轮换不属于本提交已验证范围。发布仍须满足全部必需 CI、正式更新日志与生成页面门禁，不降低或跳过门禁。
