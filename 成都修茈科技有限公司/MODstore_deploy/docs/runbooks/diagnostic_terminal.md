# XC 统一诊断终端

XC 统一诊断终端是一条只读快速通道，用来在同一个入口定位账号、客户交付、调度任务、系统事件、受控错误日志、API 路由和部署版本。它不执行 Shell，也不修改套餐、订单、付款、交付或事件数据。

## 网页入口

- 主管理端：`https://www.xiu-ci.com/admin/diagnostic-terminal`
- MODstore 运维端：`https://www.xiu-ci.com/market/admin/ops-terminal`

页面打开后自动执行 `doctor`。也可点击常用命令、输入命令、用方向键浏览历史，或按 `Command/Ctrl + K` 聚焦输入框。结果可以复制或导出为 JSON。

## 服务器快捷模式

在当前发布目录运行：

```bash
cd /opt/xcmax/current/成都修茈科技有限公司/MODstore_deploy
python3 scripts/xcmax_terminal.py doctor
python3 scripts/xcmax_terminal.py problems
python3 scripts/xcmax_terminal.py find 登录 --limit 20
python3 scripts/xcmax_terminal.py account SUNBIRD --json
python3 scripts/xcmax_terminal.py logs error --limit 20
python3 scripts/xcmax_terminal.py routes health
```

如果已按 Python 项目安装，也可直接运行 `xcmax-terminal`。CLI 会读取项目环境以及 `/etc/xcmax/modstore.env`、`/etc/xcmax/modstore-release.env`；也可以用 `--env-file` 指定环境。没有明确数据库配置时会拒绝落到默认 SQLite，避免查错库。

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
| `routes [关键词]` | 查询在线 API 路由 |
| `version` | 查询 SHA、发布标识和产物哈希 |
| `help` | 查看命令帮助 |

## 安全边界

- 命令由白名单解析器执行，长度、结果数量和参数均有限制；`shell`、任意路径及未知选项会被拒绝。
- 日志只读取 `OPS_NGINX_ERROR_LOG`、`MODSTORE_APP_ERROR_LOG` 配置的文件，最多读取文件尾部 256 KiB。
- 密码、令牌、Bearer、API key 等常见密钥形态在结果返回前脱敏。
- 网页接口仅管理员可调用；服务端 CLI 可用 `--actor` 再校验管理员账号。
- `deferred` 表示策略等待，不等同于执行失败；体检会与 failing/stale 分开报告。
