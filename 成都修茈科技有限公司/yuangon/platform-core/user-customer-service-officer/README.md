# 用户客服员工（`user-customer-service-officer`）

## 一句话职责

面向**终端用户**的客服 AI 员工：绑定 Mac 微信账号资产，在「内部客服」页工作；首要能力为**需求采集**（生成话术 + 推送落地页表单链接）。

## 与现有模块的区别

| 模块 | 角色 |
|------|------|
| **内部客服**（页面） | 管理员总机 UI，本员工的工作台 |
| **外部客服**（页面） | 企业分机 → 总机联络 |
| **用户客服员工**（编制岗） | 面向 C 端用户的 AI 员工，微信沟通 + 需求采集 |
| **wechat-contacts-ai-employee**（Mod） | 微信联系人/本地 DB 数据源（资产） |
| **intake-dispatcher** | 接收表单/工单后归一化任务 |

## 资产

- **微信账号**：Mac 本地登录；通过「导入微信」+ 群聊工作台同步消息

## 首要能力：需求采集

1. 管理员在内部客服页填写**业务背景**（brief）
2. 员工生成可复制到微信的话术 + `https://xiu-ci.com/market/about` 表单链接
3. 客户填写 `landing_contact_submissions` → 后续接入 CRM / intake-dispatcher

## API

- 员工包：`POST /api/mod/user-customer-service-officer/employees/user-customer-service-officer/run`
- 客服桥接：`POST /api/mod/xcagi-customer-service-bridge/user-cs/demand-intake`

## 工作区

- `customer-service/sessions/` — 需求采集会话
- `customer-service/wechat/` — 微信 relay 元数据
