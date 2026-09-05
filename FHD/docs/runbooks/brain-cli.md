# 智脑终端

智脑的对话、运行状态、接口查询和文件修改功能通过系统终端使用。原“智脑集成”前端页面及菜单已移除，旧链接返回首页。

## 启动与登录

先启动 XCAGI 桌面端或已有 API 服务。在 FHD 源码目录使用 Python 3.11 或更新版本运行客户端：

```sh
python3 -m app.cli.brain --help
python3 -m app.cli.brain login --username YOUR_USERNAME
python3 -m app.cli.brain shell
```

密码通过隐藏输入获取，不作为命令参数。个人账号另加 `--account-kind personal`；需要动态验证码时另加 `--totp`。客户端只使用 Python 标准库，不会启动后端。安装包含本模块的 XCAGI Python 包后，同一入口为 `xcagi-brain`，例如 `xcagi-brain shell`。

仅安装终端客户端时，可在独立虚拟环境中安装可信构建的 XCAGI wheel，并省略后端依赖：

```sh
python3 -m venv ~/.venvs/xcagi-brain
~/.venvs/xcagi-brain/bin/python -m pip install --no-deps /path/to/xcagi.whl
~/.venvs/xcagi-brain/bin/xcagi-brain --help
```

将示例 wheel 路径替换为实际文件。此环境用于 CLI；运行后端仍需完整的服务依赖。

默认连接 `http://127.0.0.1:17500`。服务使用其他地址时，将 `--origin` 放在命令前，或设置 `XCAGI_BRAIN_ORIGIN`。未设置该变量时也会读取有效的 `XCAGI_DESKTOP_PORT`。远程服务须使用 HTTPS。

```sh
python3 -m app.cli.brain --origin http://127.0.0.1:17500 status
```

CLI 独立登录，不读取浏览器凭据。会话默认保存在当前用户的 `~/.xcagi-brain`，按服务地址隔离；切换账号或退出会清除原对话关联。macOS/Linux 下该目录仅当前用户可访问。`--session-dir` 可选择另一个专用私有目录。

## 日常命令

下列示例使用安装后的命令名；源码运行时可全部替换为 `python3 -m app.cli.brain`。

```sh
xcagi-brain status
xcagi-brain models --scope local
xcagi-brain models --scope cloud
xcagi-brain openapi --filter code-editor
xcagi-brain chat "你好"
xcagi-brain chat --new
xcagi-brain shell
xcagi-brain logout
```

交互终端中直接输入文字即可对话；`/new` 开始新会话，`/status` 查看状态，`/help` 查看命令，`/exit` 退出终端。退出终端会保留登录；`/logout` 才会退出账号。需要自动化读取时，将 `--json` 放在子命令前。命令失败返回非零退出码。

模型目录只说明服务列出了哪些模型，不保证模型可推理。`status` 分别显示整体健康与桌面服务状态；整体降级原因包括 `LLM_RUNTIME_UNAVAILABLE`。P2 没有只读查询接口，终端会明确显示未查询。

## 检查和修改文件

`analyze`、`draft`、`edit` 的目标路径由**服务端 `WORKSPACE_ROOT`**解析；`--file` 是终端所在机器的 UTF-8 输入文件。启动桌面服务前应为 `WORKSPACE_ROOT` 选择要操作的项目目录；默认值是桌面数据目录，不是运行 CLI 时的当前目录。

```sh
xcagi-brain analyze notes.txt
xcagi-brain edit notes.txt --file ./replacement.txt
xcagi-brain diff EDIT_ID
xcagi-brain apply EDIT_ID --confirm
```

`edit` 创建提案并返回真实 `EDIT_ID`，不会替换目标文件。查看差异后，`apply` 需要 `--confirm` 和隐藏提示输入的 P2 提升口令；脚本可以通过 `XCAGI_BRAIN_P2_TOKEN` 环境变量提供口令。不要把口令写入 shell 历史。`--create` 用于新文件，其现有服务逻辑可能提前创建父目录。

文件在提案后发生变化时，应用会因冲突失败并保留新内容。提案应用成功后不能重复应用。网络中断导致写入结果不明时，客户端不会自动重试；先读取目标文件确认实际状态。

`draft notes.txt --instruction "修改说明"` 调用现有 AI 草稿 API，需要 P2，但不会自动创建或应用提案。目前服务可能返回“代码草稿服务暂时不可用”，客户端会原样报告失败。现有代码编辑服务适用于受信任的工作区，提案存储尚不提供多人协作隔离。
