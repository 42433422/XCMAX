# XCAGI 前端

Vue、Vite 与 TypeScript 的宿主前端。依赖版本、Node 版本和脚本以 [package.json](package.json) 与锁文件为准；Node 要求至少 22.13.0。

```bash
cd FHD/frontend
npm ci
npm run dev
npm run type-check:build
npm test
npm run test:coverage
npm run test:e2e
```

开发服务器、API 代理和构建模式以 [vite.config.js](vite.config.js) 为准；使用 `VITE_API_BASE` 配置 API 地址。构建命令 `npm run build` 使用 generic 模式，`npm run build:full` 构建完整模式，严格类型检查后构建可使用 `npm run build:strict`。

覆盖率门槛和测量入口见 [覆盖率与棘轮](../docs/reports/COVERAGE_RAMP.md)。桌面交付、认证和 Mod 权限以 [文档索引](../docs/SSOT_INDEX.md) 指向的维护文档及对应代码为准。
