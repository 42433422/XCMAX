# skill-ai-asset-inventory

职责：盘点并汇报平台当前全部可用 AI 资产与接口，区分「已接线可调用」与「仅目录发现 / 产品侧未接线」。

## 适用场景

- 被问「我们现在有哪些 AI / 模型 / 接口 / 出图出视频能力」。
- 新员工入职或任务选型前确认能力边界。
- 排查「以为有 CLI 出图 / TTS 接口」类误解。

## 标准流程

1. 调用 `list_available_ai_routes`（必要时 `refresh=true`，CLI/额度 live probe 按需）。
2. 以返回的 `assets` 为准汇报，不得凭记忆补造：
   - `assets.interfaces`：HTTP / runtime / CLI 接口清单与 `available`
   - `assets.by_category`：llm / vlm / image / video / audio / embedding / rerank 计数与样例
   - `assets.providers`：各供应商已配置密钥、OAI-compat、runtime 与资产样例
   - `assets.cli_assets`：Codex/Claude/Cursor/Trae 安装与可用性；看 `product_capabilities_not_wired`
3. 分类说明调用面：

   | 资产类型 | 主接口 | 员工主路由？ |
   |---|---|---|
   | llm / vlm（runtime_selectable） | `/api/llm/chat`、runtime-route | 是 |
   | image | `/api/llm/image` | 否 |
   | video | `/api/llm/video` | 否 |
   | audio / embedding / rerank | 目录发现为主 | 否 |
   | CLI 文本兜底 | `cli.chat_fallback` | 仅本岗 API 失败时 |

4. 明确未接线事实：Codex 产品有 `image_generation`，但 XCAGI CLI 兜底未接入，须写在 risks/next_actions。

## 禁止事项

- 把目录里的 TTS/视频模型说成可 `switch_platform_llm_route` 的员工主路由。
- 声称 CLI 可生图/生视频（除非 `product_capabilities_not_wired` 已清空且有接线证据）。
- 编造未出现在 `assets.interfaces` 的路径。

## 输出契约

- summary：可用资产总览（provider 数、各类 model_count、CLI 可用数）。
- evidence：`list_available_ai_routes.assets` 关键字段摘录。
- risks：未配置密钥、OAI-compat 缺失、CLI 未安装、未接线能力。
- next_actions：补 key / 选型 / 是否立项接线某能力。
- requires_human：涉及密钥写入或新接口立项时为 true。
