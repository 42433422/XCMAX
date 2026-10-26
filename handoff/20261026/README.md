# XCMAX 接手包（2026-10-26）

**这是源码接手包，不是安装器，也不是“已经全绿、可以直接发布”的版本。**

你已接手后续执行。仓库里的独立交接分支仅新增交接附件（保留公共基线源码，不含任何新功能修改），不是产品分支，**不要把该交接分支合入 main**。本包只保存已存在的提交、独立补丁和未完成源码；导出期间没有继续修代码、提交功能代码、跑项目测试、触发项目 CI、合并或部署；交接附件按你的授权单独上传到独立交接分支，不合入 main。下列测试数字是停止前已有的结果，不是此次重新跑出的结果。

## 1. 先做什么

1. 保存 ZIP；解压后在包目录运行 `sha256sum -c SHA256SUMS`，确认文件完整。
2. 从官方仓库克隆，确认下面的共同基线存在，再导入三条独立分支。
3. **A / B / C 分开审，不要三线盲目 merge。** 交接包内的补丁与 WIP 也不是已经整合进三条分支。
4. 优先接手已有 PR 的核对与小修，再逐项解决红项。代码增长预算规则的问题仍未得到答复，原规则不改。
5. 此前对话里的“33.33”不是代码成熟度，也不是验收通过率；请以具体证据和未过项为准。

## 2. 文件分区

| 目录/文件 | 用途与边界 |
| --- | --- |
| `bundles/A.bundle` | A：harness/recovery 已提交本地分支；不是完整仓库备份 |
| `bundles/B.bundle` | B：已有 PR 2686 的本地链，包含未推送的 isort 空行修复 |
| `bundles/C.bundle` | C：ETL batch plan 已提交分支；不含下面两个未跟踪模板文件 |
| `patches/isort-fix.patch` | B bundle 已包含此改动；供单独审查，**不要在 B 上重复应用** |
| `patches/snapshot-read.patch` | 独立 snapshot 只读补丁，未整合 |
| `patches/prepare-1.0.0.7-test.patch` | Windows 测试候选准备补丁，未整合、未实装 |
| `patches/reconnect-lifetime-v5.1-NOT-READY.patch` | 完整旧取消补丁；存在 P1，**不能直接合入** |
| `WIP-C-template-NOT-INTEGRATED/` | 两个 C 线未跟踪模板源码/测试，未接 API/UI |
| `WIP-reconnect-v6-UNVERIFIED/` | 当前 v6 未封板源码/测试，仅 `.py`；不是最终可用版本 |
| `manifest.json` / `SHA256SUMS` | 导出身份、文件大小和 SHA-256，用于核对，不是测试通过证明 |

不含客户截图、客户原始文件、真实凭据、`.env`、缓存、原 research 目录、内部工作笔记/worker 报告、私有记忆或浏览器 token。测试中的合成占位数据保留。未包含约 346 MB 的 Windows exe。旧 v1–v5 源材料仍留在原工作区，本包不重复收录。

## 3. 正确导入 bundle

官方仓库：<https://github.com/42433422/XCMAX>

共同公共基线：`54d4541cbe4cd77e258163c75e3e9fc8c886b507`

三个 bundle 都只携带 **base..实际分支 HEAD** 的增量对象，保留各自广告 ref，唯一前置提交都是上述基线；不包含整个历史。不能把增量 bundle 当成完整仓库直接 clone。导出时均已通过 `git bundle verify`。

下面以 Bash / Git Bash 为例。先把 `PKG` 改成解压目录的绝对路径：

```bash
PKG='/你的路径/XCMAX-handoff-20261026'
(cd "$PKG" && sha256sum -c SHA256SUMS)

git clone https://github.com/42433422/XCMAX.git XCMAX-handoff
cd XCMAX-handoff
BASE=54d4541cbe4cd77e258163c75e3e9fc8c886b507
git cat-file -e "$BASE^{commit}"  # 缺基线就停下，先获取官方历史

for LINE in A B C; do
  git bundle verify "$PKG/bundles/$LINE.bundle" || exit 1
  git bundle list-heads "$PKG/bundles/$LINE.bundle"
done

git fetch "$PKG/bundles/A.bundle" \
  refs/heads/dot/harness-recovery-20261026:refs/heads/handoff/A
git fetch "$PKG/bundles/B.bundle" \
  refs/heads/dot/onsite-isort-repair-20261026:refs/heads/handoff/B
git fetch "$PKG/bundles/C.bundle" \
  refs/heads/feat/etl-batch-plan-c:refs/heads/handoff/C

git rev-parse handoff/A handoff/B handoff/C
git log --oneline "$BASE..handoff/A"
git diff --stat "$BASE" handoff/B
git diff --stat "$BASE" handoff/C
```

导入后的三个 HEAD 必须分别是：

- A：`a8817c4a2669cbd4b45c4b1237b23c7ef0a52fca`
- B：`97343e90d09129dbcd6d86fe13a5eacd22513a04`
- C：`4a9e120098d826c0a08a3818b742fbf315ff13cf`

需要隔离查看时，可另开 worktree；不要覆盖你现有的修改：

```bash
git worktree add ../XCMAX-A handoff/A
git worktree add ../XCMAX-B handoff/B
git worktree add ../XCMAX-C handoff/C
```

## 4. A / B / C 的最后状态与下一步

### A：harness / recovery

- 108 个基线后提交；HEAD 如上。跟踪文件干净，未提交的原 research 目录不在包内；尚未提交 PR。
- 迁移离线评测 **121/121**，相关文件回归 **200/200**。这两组证据不能当整线全绿。
- **原 JSONL 回放仍为 89/121；netgate 与 23341 门禁仍红。**
- 下一步：先复现并解决这些红项，分清离线替代验证与原始验收，别用迁移后的通过数覆盖原始失败结果。

### B：现场统一线 / PR 2686

- 本地 HEAD：`97343e90d09129dbcd6d86fe13a5eacd22513a04`
- tree：`88cae437b22f1d7b7994363fc4f7858a64c6fe9b`
- 停止时 PR 远端 HEAD 仍是：`ad11368326bc9fe28d5bd110e91982ce3990f45a`
- 本地最后一个提交只在 **1 个测试文件增加 3 条导入分组空行**，是 isort 修复；bundle 已包含。
- 记录结果：48 tests、Black（1374 文件）、isort、Flake8、聚焦 SQLAlchemy 2.0 typing 通过；**全量 mypy 137，非绿**。preflight 数值为 **-688**，不是另一个已全绿声明。
- [PR 2686](https://github.com/42433422/XCMAX/pull/2686) 已提交但未合并。截至 **2026-10-26 06:22 UTC** 最后观察为 22 成功、1 isort 失败、1 运行；云 CI 可能自行继续。已停止持续监控，接手后重新查看，不把此快照当当前状态。
- [PR 2683](https://github.com/42433422/XCMAX/pull/2683) 最后记录 HEAD 为 `74abc18f751f75c98a3962a5a4ae039fa525584d`，全绿、draft、未合并；这不表示 B 的全部工作通过。

你审完后，用**自己的 Git/GitHub 登录**推送 isort 小修。先确认 PR 分支与远端 HEAD 没有变化；只允许普通快进，不能 force：

```bash
# 在已导入 handoff/B 的仓库中；gh 使用你自己的登录。
PR_BRANCH="$(gh pr view 2686 --repo 42433422/XCMAX \
  --json headRefName --jq .headRefName)"
test -n "$PR_BRANCH" || exit 1
EXPECTED=ad11368326bc9fe28d5bd110e91982ce3990f45a
REMOTE_HEAD="$(git ls-remote --heads origin "refs/heads/$PR_BRANCH" | awk '{print $1}')"
[ "$REMOTE_HEAD" = "$EXPECTED" ] || { echo '远端已变或读取失败，停止并重新审查'; exit 1; }
git merge-base --is-ancestor "$EXPECTED" handoff/B || exit 1
git diff --stat "$EXPECTED" handoff/B
# 确认仅预期的空行小修后，由你执行：
git push origin "handoff/B:refs/heads/$PR_BRANCH"
```

若远端已变，先审查新增提交、重新对齐；不要盲覆盖或强推。

### C：ETL batch plan

- HEAD：`4a9e120098d826c0a08a3818b742fbf315ff13cf`
- tree：`b7ad00faa4bf3795fa569ac768c1bb9ffc768865`
- 已提交链的跟踪文件干净；两个模板 WIP 文件另放，未混入 bundle。
- `d381f4b...` 阶段：后端 **946 passed / 31 skipped**。
- `4a9e120...` 阶段：后端 **112 passed**，前端 **88 passed**；但最新定向 tsc 返回 **137**，不能称类型检查通过。
- counted 增加 **6239**，超 baseline **5632**，代码增长门禁仍红；不要擅自改预算规则。
- 实际模型调用 **0**。客户 CSV 与 knowledge-only 路径已有可写、去重、独立读回能力；混合三层、Persy、模板生产写入、恢复、真实模型、完整 UI 尚未完成。
- 下一步：先处理类型检查与增长预算，再补齐上述生产链路。原有 **12 次实际上游 / ¥10** 预算不扩大；不要把离线结果描述成真实模型验收。

#### C 的两个模板 WIP 文件

`WIP-C-template-NOT-INTEGRATED/FHD/` 下：

- `app/application/etl/batch_template_cells.py`：706 行。
- `tests/test_application/test_etl_batch_template_cells.py`：249 行。

已有 33 个合成测试与 ruff 通过，但只覆盖无主题单页场景；普通 Excel 主题、富文本等负测缺失。**尚未登记能力、未接 API/UI，不是生产模板写入完成。** 先逐文件审，再决定如何移入自己的工作分支。

## 5. 独立补丁：逐个审，不要一起套

普通补丁应先在干净、独立的工作分支检查上下文，例如：

```bash
git apply --stat "$PKG/patches/snapshot-read.patch"
git apply --check "$PKG/patches/snapshot-read.patch"
# 只有你审查并确认目标基线合适后，才自行 git apply。
```

本包没有替你应用这些补丁；`--check` 成功也只是上下文匹配，不是功能验收。

### snapshot-read.patch

- 3 files，+121/-20；已有 23 tests、mypy、ruff 通过，旧代码 4 个负控失败。
- 只证明 **已构造好的 service 状态下**读取快照不写锁；冷构造仍会走原有初始化。
- 未整合。不能把它描述成从初始化到读取全程无写入。

### prepare-1.0.0.7-test.patch

- 22 files，+184/-42；已有 39 tests 通过。**未实装、未整合、未构建候选。**
- 旧 from marker：`1.0.0+SHA12`；候选 to marker：`1.0.0.7+SHA12`。产品版本与完整 SHA 另行独立校验，不能只看短 marker。
- 官方当前 `.6` 测试基线：source `13fccf867a592708dbd2347ca52b30f92e899550`。
- 官方 `.6` exe SHA-256：`5d4b75c831a78185eab53787c7dfd3ebe9d066fe27daadd147e208d4666cb855`；大小 **345730149 bytes**。客户实装 SHA 未知；不要假设客户当前装的就是这份。
- 官方 pipeline：`fhd-release-desktop.yml`；候选必须让 `main` 与 `release_sha` 一致，先 `candidate_only=true` 只出候选。
- 再由 `fhd-windows-candidate-acceptance.yml` 做 **Clean / Upgrade / Gui / Recovery / Rollback**。
- 全部通过后，才把**同一个已验收产物**放官网临时 Windows 测试入口；保留旧 pointer / 旧包，不开全体 OTA。官网测试下载已获允许，但当前还没有构建可下载的新候选。

### reconnect-lifetime-v5.1-NOT-READY.patch 与 v6 WIP

- v5.1 before：`2e51f9f45179243bc17ff877569d3133ead22fd6`。
- **NOT READY**：存在 cancel 旧快照覆盖 unknown 门禁的 P1，以及晚到 receipt 问题。不要直接合入。
- `WIP-reconnect-v6-UNVERIFIED/` 只保存当前源码/测试，不是假称 v6 已修好。部分并发/审计测试曾通过，但最后恢复 `_apply_requested_control` 后没有做聚合验证。
- “cancel 先落库、observer 尚未运行就立即 retry”这条路径的修法尚未实施。
- 必须逐文件对比；**不要整树覆盖 B 中的 failed_reply CI 修复**。先补取消/晚到回执/unknown 与重试边界，再做聚合验证。

## 6. 接手检查单

- [ ] 解压、SHA-256、基线和三条 HEAD 对上。
- [ ] B：核 PR 2686 远端，普通快进推 isort 小修，重新查看实际 CI；不把旧快照当结论。
- [ ] A：保留原 JSONL 89/121 的事实，处理 netgate / 23341 红项后再准备 PR。
- [ ] C：处理 tsc 137、增长门禁与未完成生产链路；模板 WIP 单独审。
- [ ] snapshot 补丁验证冷/热构造边界后再整合。
- [ ] 取消/重连 v5.1 不合；v6 先修已知问题并重新聚合验证。
- [ ] Windows：先同 SHA 候选与五项验收，再临时官网入口；不触发全体 OTA。
- [ ] 所有真实模型调用、客户文件与登录凭据仍按原授权边界处理，预算不扩、token 不搬。
