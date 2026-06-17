# 太阳鸟定制安装包 · 内嵌业务数据 SSOT

由 `scripts/package/build-sunbird-seed.py` 生成/刷新，再由 `build-sunbird-installer.ps1` 打成 zip 嵌入 WPF 安装程序。

| 路径 | 内容 |
|------|------|
| `424/考勤-2026-3月份考勤统计表.xlsx` | 固定考勤模板 |
| `data/mod_dbs/taiyangniao_pro.db` | Mod 侧库（含人员镜像） |
| `config/sunbird-roster.json` | 主库花名册种子 |
| `mods/` | 打包时由 `build-sunbird-installer.ps1` 从 `mods/taiyangniao-pro`、`mods/attendance-industry` 拷贝 |

刷新种子：

```bash
cd FHD && python3 scripts/package/build-sunbird-seed.py
```

服务器交付授权：

```bash
cd /root/XCMAX/成都修茈科技有限公司/MODstore_deploy
export DATABASE_URL="$(grep '^DATABASE_URL=' .env | tail -1 | cut -d= -f2-)"
.venv/bin/python scripts/provision_enterprise_delivery.py --delivery sunbird
```

该授权会把市场账号 `SUNBIRD` 标记为企业账号，并绑定 `attendance-industry` 与 `taiyangniao-pro`。
