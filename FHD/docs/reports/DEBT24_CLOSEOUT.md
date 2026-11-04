# 24 项余债一次性收口对照表

基准：`fd7c00034` → 分支 `debt/24-closeout`  
时间：2026-10-25 Asia/Shanghai  
约束：语义不变；hotfix `a8850107` 不动；本轮不部署生产。

## 改前 / 改后 / 处置

| # | 项 | 改前 | 改后 | 处置 |
|---|----|------|------|------|
| P1-1 | MODstore `_part_*` 机械碎片 | 258（G10 口径） | **0** + 37×`*_merged.py` | 按 stem 合并；G10 棘轮=0 |
| P1-2 | application 测试样例逃逸 | `examples.py` 同 blob；`_SPECIAL_TEST_FIXTURES` 运行时依赖 | `special_tool_contracts.py` + `_SPECIAL_TOOL_CONTRACTS`；`contract_samples` 字段；schema parts 合并 | 诚实改名+G3 禁符号逃逸 |
| P1-3 | legacy | 61文件/48py；prod refs **54** | 目录仍在（真引用）；prod refs **23** | 清文档假引用；disposition；G4=23 |
| P1-4 | 巨型矩阵测试 | behavior 322KB；score 191KB | behavior ~55KB；score ~5KB+14KB JSON | 生成器/轴编码；烟测通过 |
| P1-5 | 版本 SSOT | 候选1.0.0.6 vs 已发布1.0.0.5 混 | `PRODUCT_VERSION_SSOT.md` | 四层口径 |
| P1-6 | evidence/树体积 | 全树~620.5MiB；evidence~407.5MiB | evidence≈**12.91MiB**；全索引≈**182.74MiB** | round2 外置 930 文件≈394.6MiB |
| P1-7 | py>40KB | 156 / 124 | 175 / 123 | G11 锁定（合并模块变大，测试巨型下降） |
| P2-8 | domain/ports 旧3 | 3 py | 保留共享 + 文档 | DEBT24_P2_CLOSEOUT |
| P2-9 | NeuroBus/security | 边界文档已有 | 不灌空文件 | 沿用 BOUNDARY/SSOT |
| P2-10 | 同名副本 | G8=0 | 保持 | G8 |
| P2-11 | 多入口/SKU | 缺清单 | `docs/ENTRYPOINTS_SKU.md` | 官方/兼容/遗留 |
| P2-12 | LangGraph vendored | 缺治理 | `LANGGRAPH_VENDORED.md` + verify 钩子 | WARN 钩子 |
| P2-13 | kellai | 缺说明 | `docs/KELLAI_SUBMODULE.md` | 用途/维护/合规 |
| P2-14 | 变异测试 | 易误读全仓95% | `MUTATION_TESTING_SCOPE.md` | 限定范围 |

## 复核命令

```bash
git ls-tree -r -l HEAD | awk '{s+=$4} END{printf "tree MiB=%.2f\n", s/1024/1024}'
git ls-tree -r -l HEAD -- FHD/docs/evidence/ | awk '{s+=$4} END{printf "evidence MiB=%.2f\n", s/1024/1024}'
python3 FHD/scripts/ci/check_structure_gates.py --repo . --fail-on-warn
```

## 已澄清勿重开

六份 LangGraph fork、DEPLOY 无主从、变异从未公开、架构纹丝不动。
