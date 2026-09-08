# 隔离路由注册清单与分发冲突修复

当前 profile 是 pytest 隔离环境下 register_all_routes、开启 legacy compatibility，不启动 lifespan，不执行业务端点。完整清单见 [runtime-contracts.json](runtime-contracts.json)，附源码与审计器哈希。

| 指标 | 修复前 | 修复后 | 含义 |
| --- | ---: | ---: | --- |
| API 注册条目 | 1017 | 1013 | 包含重复的路径/方法注册 |
| 不同路径/方法 | 1013 | 1013 | 此注册配置的接口分母，不是独立业务功能总数 |
| 重复路径/方法 | 4 | 0 | health GET 与 LAN settings GET/POST/PUT |
| 静态路径被前序路由遮挡 | 6 | 0 | 含重复注册及两个标签打印路径 |
| 可读取协议 | 1009 | 1013 | 协议可读不代表有权限或业务已实现 |

LAN 配置只由 lan_settings_routes 注册 HTTP 入口；保留旧函数供 SDK 调用。/api/health 由健康挂载统一提供，旧 /health 别名保留。通用文件打印路径排在具体标签动作之后，不再抢先匹配 single_label 和 pdf_labels。

真实 HTTP 分发验证 single_label 到达标签服务（打印机使用替身，没有发送实际打印任务）；pdf_labels 正确返回既有 501 未实现状态，不再变成文件不存在。这项 PDF 标签业务能力仍待完成。

## 重现

在 FHD 目录使用项目 Python 运行：

```sh
XCMAX_API_CONTRACT_REPORT=docs/evidence/ai-full-control/runtime-contracts.json python -m pytest tests/test_application/test_aiopen_runtime_inventory.py -q
```

报告输出为显式选择；普通测试不会改写证据文件。静态扫描器可另行刷新 source-surfaces.json 并对照源码哈希。

## 边界

- 动态路径之间的重叠仍需具体请求验证。
- 非 API catch-all 挂载、中间件和账号权限可能进一步影响分发。
- 未启动生命周期，不包含启动后才加载的全部客户 Mod、原生端或安装端状态。
- 未执行全部接口，不声明业务覆盖率；全软件完成率仍未知。
