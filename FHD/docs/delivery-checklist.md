# 企业版桌面端交付前检查单

## 登录与账号
- [ ] 企业版默认连接生产认证服务器（`https://xiu-ci.com`），不暴露 MODstore/本地地址/开发脚本
- [ ] 登录失败文案为「无法连接服务器，请检查网络后重试」，无内部技术细节
- [ ] 企业/管理员登录分流正常

## 通用化（无客户预设）
- [ ] 交付构建使用 `enterprise` edition（enterprise SKU，`npm run build:enterprise` / `--mode enterprise`）
- [ ] 安装包不含 `taiyangniao-pro`、`sz-qsm-pro`（`SKU_EXCLUDED_FROM_BUNDLE` 已排除）
- [ ] `protected_client_mod_ids` 默认空，Mod 全量走账号权益动态加载
- [ ] 通用交付设置环境变量 `XCAGI_GENERIC_DELIVERY=1` 跳过演示账号 seed
- [ ] 核心菜单与路由标题为中性通用措辞

## 安全（单租户）
- [ ] API 从会话解析用户，不信任 `X-User-ID` 自报头
- [ ] `X-Tenant-Id` 从登录用户绑定，不可伪造
- [ ] `/api/auth/me` 返回 `tenant_id` 与权限
- [ ] 业务查询已接线 `apply_data_scope`

## IM 与消息
- [ ] 侧栏有「消息」入口，路由 `/im`
- [ ] IM 绑定登录态，WS 会话校验，断线自动重连
- [ ] 统一 Toast（`useAppToast`）替代 error-handler 占位
- [ ] IM notify-only 模式触发浏览器/桌面系统通知
- [ ] 桌面端支持角标（`setBadge` IPC）
- [ ] 音效文件 `public/sounds/im-in.wav`、`im-send.wav` 存在

## 桌面壳
- [ ] 自动更新：`update-available` 后自动 `downloadUpdate`
- [ ] enterprise 加载无 `?shell=1`，完整侧栏
- [ ] CSP 与外链拦截生效
- [ ] `env.d.ts` 与 preload API 类型同步

## 打包
- [ ] personal + enterprise 双 SKU dist 产物可生成
- [ ] 更新源按 SKU 分离（`update.xcagi.com/releases/stable/{sku}/`）
- [ ] 前后端测试 baseline 通过
