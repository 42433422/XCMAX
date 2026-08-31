# XC 统一诊断终端

XC 统一诊断终端是一条服务器 CLI 只读快速通道，用来定位账号、客户交付、调度任务、系统事件、受控错误日志、API 路由和部署版本。它不提供管理端页面或专用 HTTP 接口，不执行 Shell，也不修改套餐、订单、付款、交付或事件数据。

## 服务器快捷模式

生产发布会安装稳定入口 `/usr/local/bin/xcmax-terminal`，直接运行：

```bash
xcmax-terminal doctor
xcmax-terminal problems
xcmax-terminal find 登录 --limit 20
xcmax-terminal account SUNBIRD --json
xcmax-terminal logs error --limit 20
xcmax-terminal --openapi-url http://127.0.0.1:8791/openapi.json routes health
```

在仓库开发环境中可以执行 `.venv/bin/python scripts/xcmax_terminal.py`；即使误用系统 `python3`，入口也会自动切换到项目 `.venv`。CLI 会读取项目环境以及 `/etc/xcmax/modstore.env`、`/etc/xcmax/modstore-release.env`；也可以用 `--env-file` 指定环境。没有明确数据库配置时会拒绝落到默认 SQLite，避免查错库。

需要校验操作人时使用 `--actor <管理员账号>`。`--json` 输出机器可读结果。退出码为：`0` 正常或需关注、`1` 发现降级问题、`2` 命令或权限校验失败。

## 命令

| 命令 | 用途 |
| --- | --- |
| `doctor` | 一次体检数据库、版本、调度、未解决 DLQ、近 24 小时事件与安装失败、客户交付卡点 |
| `problems [关键词]` | 只列当前异常与需关注证据 |
| `find <关键词>` | 跨账号、交付、任务、事件、DLQ 和运行时路由搜索 |
| `account <账号>` | 查询账号、有效套餐和交付状态 |
| `delivery [关键词]` | 查询永久购买账号的标准交付台账 |
| `scheduler [关键词]` | 查询任务并区分 failing、stale、deferred |
| `incidents [关键词]` | 查询系统事件账本 |
| `logs [关键词]` | 查询事件、DLQ 和配置允许的错误日志 |
| `routes [关键词]` | 查询 `--openapi-url` 指定的本机 API 路由 |
| `version` | 查询 SHA、发布标识和产物哈希 |
| `help` | 查看命令帮助 |

## 安全边界

- 命令由白名单解析器执行，长度、结果数量和参数均有限制；`shell`、任意路径及未知选项会被拒绝。
- 日志只读取 `OPS_NGINX_ERROR_LOG`、`MODSTORE_APP_ERROR_LOG` 配置的文件，最多读取文件尾部 256 KiB。
- 密码、令牌、Bearer、API key 等常见密钥形态在结果返回前脱敏。
- 不注册诊断页面或专用 HTTP 接口；服务端 CLI 可用 `--actor` 校验管理员账号。
- `deferred` 表示策略等待，不等同于执行失败；体检会与 failing/stale 分开报告。
