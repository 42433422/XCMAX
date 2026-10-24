# 审计项 18–31 一次性收口对照表

测量点：main `fe810a415` → 本列车；时区 Asia/Shanghai。

| 项 | 改前 | 改后 | 处置 |
|----|------|------|------|
| 18 application:domain | 626:116（5.40:1） | 608:143（4.25:1） | **已改**：ports/services 归域；G9 棘轮 ≤4.50:1 |
| 19 domain/services 胀 | 17 文件；coordinator 17.6KB | conversation→`domain/conversation/services`；shipment/product services 归域；coordinator 拆 `coordinator_types.py`（~15.6KB+3.5KB） | **已改**；旧路径 shim |
| 20 ports 三处分散 | app 15 / wf 5 / domain\<ctx\> 1 | app 1 / wf 1 / domain\<ctx\> 7 | **已改**；G5 基线降至 1/1 |
| 21 fastapi_routes | 312 / top 117 | canonical≤305 / top 115；excel part 碎片删除 | **已改+棘轮**；G2 基线收紧 |
| 22 security 薄 | 15 文件 | +`security/SSOT.md` + 边界测试 | **已改**（补 SSOT/测试，不灌空文件） |
| 23 neuro_bus 叙事 | 110 文件 | +`neuro_bus/BOUNDARY.md` 标明稳定入口与废弃面 | **已改**（边界文档；不虚增） |
| 24 test_fixtures in application | 2 豁免 | 0；改名为 `tool_spec_data/examples.py` + `contract_samples.py` | **已改**；G3 豁免清空 |
| 25 legacy | 48 py / 54 prod refs | legacy_vo→domain.shipment.value_objects；prod refs 棘轮 54 | **部分**：引用未归零故不物理删；删除条件见 09 |
| 26–28 机械拆分/超长名/贴线 | mixin 11；part 碎片 4；名>60：0 | 碎片 **0**；G7 禁止再增；mixin 基线收紧 11/0/1 | **已改+门禁** |
| 29–31 同名泛滥 | mods 内 blueprints 等为员工包契约 | **有意保留（mods/XCAGI）**；`FHD/app` 内 noisy basename **0** + G8 棘轮 | **门禁+保留理由** |

## 门禁

`FHD/scripts/ci/check_structure_gates.py`：G1–G9；CI `source-governance` `--fail-on-warn`。

## Legacy 物理删除条件（项 25）

生产 `app.legacy` 引用归零（或豁免表到期清空）后另 PR 删 `FHD/app/legacy/**`；本列车不删仍被 mounts/tests 引用的 compat。
