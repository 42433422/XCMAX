# 软著申请材料

本目录存放 **XCAGI 企业 AI 员工平台** 软件著作权登记的**生成脚本**与说明。大体积产物（`*.txt` / `*.pdf` / `源代码统计报告.md`）已加入 `.gitignore`，需本地重跑后提交版权中心。

**版本号以仓库根 [`VERSION.md`](../../VERSION.md) 为准**（当前 GA：**10.0.0**）。生成 PDF 前请同步脚本内页眉/版本字符串。

## 项目基本信息

- **软件全称**：XCAGI 企业 AI 员工平台
- **版本号**：10.0.0（与 `VERSION.md`、发版锚点一致）
- **著作权人**：李佳泷（个人/自然人申请）
- **开发完成日期**：按实际冻结日填写（建议与 CHANGELOG v10.0.0 日期对齐）
- **项目性质**：跨平台企业 AI 员工桌面平台（桌面 + Web 自托管）

发版与商店缺口说明见 [`docs/guides/RELEASE_GAP_CLOSURE_COMPLETE.md`](../../docs/guides/RELEASE_GAP_CLOSURE_COMPLETE.md)。

## 目录内容

| 类型 | 文件 | 说明 |
|------|------|------|
| 脚本 | `源代码文档生成器.py` | 扫描 `frontend/src` 与 `app`，输出前后端 txt |
| 脚本 | `合并源代码文档.py` | 合并为 `完整源代码.txt` |
| 脚本 | `生成 PDF 文档.py` / `gen_pdf.py` | 源代码 PDF（前 30 + 后 30 页） |
| 脚本 | `gen_manual.py` | 软件说明书 PDF |
| 生成物（本地） | `*源代码*.txt`、`*.pdf` | 运行脚本后产生，**勿提交 git** |

## 重新生成材料

```bash
cd FHD/XCAGI/软著申请

python3 源代码文档生成器.py
python3 合并源代码文档.py

# PDF 需 reportlab（示例：项目 .venv-cov）
../.venv-cov/bin/python "生成 PDF 文档.py"
../.venv-cov/bin/python gen_manual.py
```

生成前在 `gen_manual.py` 与 PDF 页眉中确认：**软件名、版本号 10.0.0、著作权人、开发完成日期** 与 [`VERSION.md`](../../VERSION.md) 一致。

## 官方入口与材料

- 中国版权保护中心：https://www.ccopyright.com.cn
- 个人申请需：R11 申请表、源代码 PDF、说明书 PDF、身份证、非职务开发保证书

详细流程、补正踩坑与自查清单见本目录历史说明（2026-05 编写）；提交前对照版权中心当年表格为准。
