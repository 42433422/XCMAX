# Git 工作树恢复指南（迁移/重组期）

## 症状

- `git status` 报：`fatal: not a git repository: E:/FHD/.git/worktrees/...`
- 或大量 `D` / `??`，与 IDE 里实际文件不一致
- 仓库根在 **`E:\XCMAX\FHD`**（独立 `.git` 目录），勿与旧路径 `E:\FHD` 混用

## 安全诊断

在 PowerShell 中：

```powershell
cd E:\XCMAX\FHD
git rev-parse --show-toplevel
git status -sb
git diff --stat HEAD
```

若 `rev-parse` 失败，检查 `.git` 是否为目录且完整（非损坏的 worktree 指针）。

**已知的 prunable worktree 修复**（`E:/FHD` → `E:/XCMAX/FHD`）：

```powershell
# .push-v5-worktree/.git 与 .git/worktrees/-push-v5-worktree/gitdir 改为 XCMAX 路径
git worktree prune -v
git status -sb
```

或运行：`scripts/dev/git_change_inventory.ps1` 生成 `git-change-inventory.txt`。

## 推荐流程

1. **冻结迁移批次**：先提交「构建可绿」变更（generic glob、测试修复），再处理大规模 `D`/`??`。
2. **区分三类变更**  
   - 预期删除（已迁到 `XCAGI/`、`mods/`）→ `git add -u`  
   - 误删 → `git checkout HEAD -- <path>` 或从备份恢复  
   - 新文件 → 按目录分批 `git add`
3. **勿在脏树上 force push**；需要备份时：`git stash push -u -m "pre-migration"` 或复制整个 `FHD` 目录。

## 辅助脚本

```powershell
.\scripts\dev\git_status_safe.ps1
```

（输出 top-level、简短 status、未跟踪数量。）

## 与 CI 的关系

GitHub remote：`https://github.com/42433422/ai-excel-helper.git`（见 `.git/config`）。  
推送前在本地跑：`CI_STABLE_ONLY=1` pytest + `npm run build:generic`。
