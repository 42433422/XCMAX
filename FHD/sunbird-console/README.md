# 太阳鸟企业壳（sunbird-console）

修茈太阳鸟客户专属前端，与通用宿主 `frontend/`、平台运维 `admin-console/` 分离构建。

| 项 | 说明 |
|----|------|
| 源码 | `sunbird-console/src`（账号绑定、ERP 路由、太阳鸟 Mod 策略等） |
| Mod 页面 | `mods/taiyangniao-pro/frontend`（考勤表转换等） |
| 共用 | `frontend/src`（布局、登录、stores） |
| 开发 | `npm run dev` → 默认 **:5012** |
| 构建 | `npm run build` → `FHD/templates/sunbird-vue-dist/` |
| 访问 | **http://127.0.0.1:5003/sunbird/** |

通用 SKU 不再默认 `taiyangniao-pro`；太阳鸟账号登录后会跳转到 `/sunbird/#/taiyangniao-pro`。

## 发版

```bash
cd FHD/frontend && npm run build:full
cd FHD/admin-console && npm run build
cd FHD/sunbird-console && npm run build
```

Vite 配置：`frontend/sunbirdConsole.vite.config.js`
