# PRODUCT_VERSION_SSOT

> **SSOT（唯一真相源）**：版本叙事单一入口。数字权威仍是 [`FHD/VERSION.md`](../../VERSION.md)；本文件裁定**已发布 / 候选 / 构建 / 客户运行**四层关系，并挂漂移检测。

更新：2026-10-25（Asia/Shanghai）— debt24 closeout

## 四层口径

| 层 | 当前值 | 权威来源 | 说明 |
|----|--------|----------|------|
| **源码候选（product）** | `1.0.0.6` | `FHD/VERSION.md` | 未晋级客户前只是候选 |
| **工具链三段映射** | `1.0.0` | 同上 | npm/Electron/Flutter/Apple MARKETING |
| **已公开 Release / 客户可装** | 以线上 `/download-release.json` 与 GitHub Release 为准（审计时常见 `1.0.0.5`） | 发布产物，不是 VERSION.md | **不得**把候选 1.0.0.6 说成已发布 |
| **客户实际运行** | 部署 SHA + 制品 versionName | `ops/releases/*.json` 与运行时 health | 与候选数字可不同；以 SHA 为准 |

历史「v7」叙事是文档世代标签，**不是**第三个生产版本号。

## 漂移规则（可执行）

1. `FHD/scripts/dev/verify_version_anchors.py`：源码锚点必须等于 `VERSION.md`。
2. 公开站点 `成都修茈科技有限公司/site/data/public-site.json` 中的 `app_version` 若仍为已发布版（如 `1.0.0.5`），必须在字段旁或本 SSOT 标明「已发布」，不得与候选混写为「当前稳定」。
3. CI / release approval 的 `product_version` 必须与当次发布意图一致：候选构建用 `1.0.0.6`；客户交付物标签不得超前于已授权 Release。

## 本轮处置

- 明确：`1.0.0.6` = 源码候选；`1.0.0.5` = 已公开交付常见值。
- 不在未授权情况下改动 hotfix 指针 `a8850107` 或生产部署。
- 门禁：`verify_version_anchors.py` + 文档新鲜度（见 `docs/CI_SSOT.md`）。
