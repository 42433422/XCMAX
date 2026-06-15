# sz-qsm-pro（奇士美 PRO）

涂料行业 **账号定制 Mod**（legacy id）；与中性行业包 `coating-industry` 配对。

- 定制 mod id：`sz-qsm-pro`
- 行业包：`coating-industry`（见 `config/industry_mod_aliases.json`）
- 客户品牌：见 `config/customer_delivery.json`

## 职责（与考勤 `taiyangniao-pro` 对齐）

| 能力 | 所在 Mod |
|------|----------|
| 行业词汇 / 中性门面 | `coating-industry` |
| 产品/客户侧栏、菜单覆盖 | `sz-qsm-pro` |
| 涂料 AI 员工、`wechat_phone` | `sz-qsm-pro` `workflow_employees` |
| phone-agent API | `sz-qsm-pro` `/api/mod/sz-qsm-pro/phone-agent/*` |

完整生产包解压到 `FHD/mods/sz-qsm-pro/` 后执行 `python FHD/scripts/dev/mods_ssot.py sync`。
