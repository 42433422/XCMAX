# 工作区体积：含 `.git` vs 尽调交付树

测量日期：**2026-06-05**（仓库：`Desktop/XCMAX/FHD`）

## 结论速览

| 口径 | 命令思路 | 约体积 | 说明 |
|------|----------|--------|------|
| **含 Git 对象库** | `du -sh FHD` | **~11G**（gc 尝试后；此前 ~9.7G） | 尽调 `du -sh Desktop/XCMAX` 会扫到 `FHD/.git` |
| **仅 `.git`** | `du -sh FHD/.git` | **~9.4G** | 历史大对象/提交留在对象库，是 M0「≤8G」未达标主因 |
| **交付树（不含 `.git`）** | 见下文「交付树 du」 | **~1.4G** | 源码、配置、占位 `ARCHIVE_POINTER`；大模型/venv/node 已外置 |

计划目标（[`specs/plan-2026-06.md`](../../specs/plan-2026-06.md) M0）：工作区 **≤8GB** — 当前 **未达标**（因 `.git`，非交付树膨胀）。详见 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)。

## 含 `.git` 的 du

在 macOS 上：

```bash
cd /Users/a4243342/Desktop/XCMAX/FHD
du -sh .          # 工作区根（含 .git）
du -sh .git       # 仅对象库
```

在仓根 `Desktop/XCMAX`：

```bash
du -sh /Users/a4243342/Desktop/XCMAX   # 整个尽调工作区（含 FHD/.git）
```

**解读**：对外声称的「工作区 8G」若用 `du -sh XCMAX` 或 `du -sh FHD`，数字会被 `.git` 主导；与「可交付源码树」不是同一口径。

## 交付树 du（不含 `.git`）

macOS `du` 无 `--exclude`。推荐只加总顶层项（不含 `.git`）：

```bash
cd /Users/a4243342/Desktop/XCMAX/FHD
du -ch $(find . -maxdepth 1 ! -name . ! -name .git -print) | tail -1
```

可选：与 Git 跟踪文件交叉核对（不含未跟踪大目录时偏小）：

```bash
git ls-files -z | xargs -0 du -ch 2>/dev/null | tail -1
```

**解读**：交付树 ≈ 尽调时仍留在工作区的源码与配置；**~1.4G** 量级（2026-06-05）。可重建依赖（venv、前端 `node_modules`）与 bulk（models、installer 等）已迁出，见各目录 `ARCHIVE_POINTER.md` 与 [`Desktop/XCMAX/ARCHIVE_POINTER.md`](../../../ARCHIVE_POINTER.md)。

## `git gc --aggressive` 尝试记录

在 `FHD` 根执行：

```bash
git gc --aggressive
```

| 项 | 结果 |
|----|------|
| 退出码 | **0** |
| `.git` 体积（`du -sk .git`） | **9897332 KB → 9889728 KB**（约 **-7.5 MB**） |
| `du -sh FHD` | gc 后约 **11G**（此前约 **9.7G**；可能与未完成清理的 pack 临时文件有关） |
| 权限/清理 | 大量 **`warning: unable to unlink ... Operation not permitted`**（约 **4.8 万** 条），无法删除旧 loose objects / 部分 `tmp_pack_*` |
| 残留 | `.git/objects/pack/` 下曾见 `tmp_pack_*`（合计约 **68M** 量级） |

**建议**：若需真正缩小 `.git`，在本机终端（非受限沙箱）重跑 `git gc --prune=now`，或评估 `git filter-repo` / 新克隆浅历史；沙箱内 gc **不能**作为已完成的瘦身手段。

## 恢复 Python venv / 前端依赖

实体在 `~/XCMAX-archives/m0-venv-20260605/`。自 `Desktop/XCMAX` 或 `FHD` 父目录执行：

```bash
export VR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-venv-20260605"
rsync -a "$VR/FHD/.venv-20260605-rebuild/" "$(pwd)/FHD/.venv/"
rsync -a "$VR/FHD/.venv-mypy/" "$(pwd)/FHD/.venv-mypy/"
rsync -a "$VR/FHD/frontend/node_modules-20260605-rebuild/" "$(pwd)/FHD/frontend/node_modules/"
```

**从零重建**（无外置包时）：

```bash
cd /Users/a4243342/Desktop/XCMAX/FHD
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # 以仓库实际依赖文件为准
python3 -m venv .venv-mypy
# frontend: cd frontend && npm ci
```

## 相关文档

- [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md) — 计划声称 vs 实测
- [`M0-remaining-gaps.md`](M0-remaining-gaps.md) — M0 未闭环项
- [`ARCHIVE_POINTER.md`](ARCHIVE_POINTER.md) — 本目录 bulk 文档外置说明
