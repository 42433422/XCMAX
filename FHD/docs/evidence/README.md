# 证据素材已外置

`FHD/docs/evidence/` 的实体内容（2629 文件 / 410MB，含 165 个验收录像）已于 2026-11-12 迁移到私有迁移仓，公开仓不再保留副本。

- 归档位置：[`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) → `sources/xcmax/FHD/docs/evidence/`
- 校验清单：归档目录内 `MANIFEST.txt`（逐文件 SHA-256 + 字节数）
- 迁移台账：`ledger/MIGRATION_LEDGER.csv` 第 `A15-001` 行

需要重新推导能力中心的验收状态时，恢复归档目录或设置环境变量：

```bash
export XCAGI_EVIDENCE_ROOT=/path/to/xcmax-Li/sources/xcmax
python3 '成都修茈科技有限公司/ops/scripts/build_capability_center.py' --check
```

未设置该变量时，`build_capability_center.py --check` 会输出 WARN 并跳过证据校验（官网仍使用已提交的公开副本 `web/capabilities/assets/evidence/`），生成模式则直接失败并提示恢复方式。
