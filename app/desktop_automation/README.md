# 通用桌面自动化

VLM 切图建库 + 模板/YOLO 快执行 + MCP 可插拔。

## 原则

1. VLM 只负责「认识界面」，不负责每次点击。
2. 模板库是长期资产；UI 改版只增量 bootstrap。
3. 双平台 = 一套 Profile/Workflow，两套 Driver。
4. MCP 是驱动实现之一。
5. 员工只编排 workflow。

## 目录

- `FHD/app/desktop_automation/` — 核心库
- `FHD/data/desktop_profiles/` —  bundled AppProfile（wechat, safari）
- `FHD/data/desktop_automation/templates/` — 运行时模板库
- `FHD/resources/desktop_automation/run_mcp_desktop.py` — MCP stdio

## API

- `GET /api/desktop/automation/status`
- `GET /api/desktop/automation/profiles`
- `POST /api/desktop/automation/workflow/run`
- `POST /api/desktop/automation/send`
- `POST /api/desktop/automation/bootstrap`
- `GET /api/desktop/automation/find-element`

## MCP 配置示例

```json
{
  "mcpServers": {
    "desktop-automation": {
      "command": "python",
      "args": ["FHD/resources/desktop_automation/run_mcp_desktop.py"],
      "cwd": "FHD"
    }
  }
}
```
