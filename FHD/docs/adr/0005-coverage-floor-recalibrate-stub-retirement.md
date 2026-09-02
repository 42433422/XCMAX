# ADR-0005 coverage floor 重校准：stub 清零后总口径与真实行为口径合一（88/81 → 78/69）

- 状态：已采纳（2026-09-01）
- 决策者：DevOps / 工程负责人
- 关联 Spec：`.trae/specs/converge-desktop-acceptance-tech-debt/spec.md` D2-5
- 前置 ADR：[ADR-0001](0001-coverage-behavior-gate.md)（行为口径硬 gate）
- 涉及文件：
  - `pyproject.toml` `[tool.coverage.report] fail_under`（88 → 78）
  - `metrics/coverage_ratchet_baseline.json`（`backend_lines_floor` 88 → 78、`backend_branch_floor` 81 → 69）
  - `metrics/coverage-dual-summary.json`（`ratchet_floors` / `quality_gate` 同步）
  - `scripts/dev/count_coverage_ramp_stubs.py`（配额基线 82 → 0，门禁保留）
  - `tests/**`（82 个 `test_coverage_ramp_*.py` 去前缀迁出）

## 背景

ADR-0001 已把后端覆盖率**唯一硬 gate** 切换为行为口径（`pytest -m 'not coverage_ramp'`，
floor 78 行 / 69 分支），但全量口径（含 stub）仍保留 88/81 的 floor 与对外宣称。两套口径
长期并存造成宣称分裂：对外数字（~88%）被 `coverage_ramp` stub 注水，真实行为覆盖
（79.26% 行 / 70.87% 分支，2026-07-25 实测）低约 9pt。

D2-5 决定将 82 个 stub 全部处置：审计确认它们并非纯占位（零 `assert True`，全部 82 个
文件含 `==` / `pytest.raises` / `status_code` 等真实行为断言共 5,202 处、4,683 个用例），
故按"含真实行为断言 → 迁出为契约测试"处置：全部**去 `test_coverage_ramp_` 前缀重命名**
（如 `test_coverage_ramp_phase4_p28_backend.py` → `test_phase4_p28_backend.py`），无删除。

## 决策

1. stub 配额基线收口至 0：`count_coverage_ramp_stubs.py --bump`（82 → 0），
   `--check` 门禁保留（新增 stub 即违规）。
2. 总口径 floor 下调至真实行为口径起点：
   - `fail_under`（行 floor SSOT）：88 → 78
   - `backend_branch_floor` / dual-summary `branch_floor`（分支 floor SSOT）：81 → 69
3. `behavior_floors`（78/69）保持不变——stub 清零后迁出的用例进入行为口径，
   行为实测只会上升，floor 无需变动。
4. `last_measured` 历史实测快照（88.19/81.5 与 79.26/70.87，2026-07-25）保留不动，
   仅作趋势参考，不参与门禁。
5. `coverage_ratchet.py` 脚本逻辑不变：两套 floor 数值合一后，`--check`（总口径）与
   `--check --behavior`（行为口径）语义自然一致，均为单一 78/69 口径。
6. conftest 的 `coverage_ramp` 打标逻辑与 pyproject marker 保留，防止前缀复活。

## 为什么下调是合理的

本次下调不是"降低质量要求"，而是**消除注水**：
- 旧 88/81 口径中约 9pt 来自 stub 的行填充，不代表行为质量；
- 新 78/69 即 ADR-0001 已采纳的行为口径硬 gate（唯一实际生效的后端门禁），本次只是把
  名义口径对齐到已生效的硬 gate；
- floor 只升不降的棘轮语义不变：CI 首次全绿后应通过 `coverage_ratchet.py --bump
  --behavior`（以及总口径 `--bump`）把 floor 棘轮到真实实测值。

## 后果

- **正面**：对外宣称与门禁口径唯一化（78/69），stub 注水彻底退出历史；
  迁出的 4,683 个用例纳入行为口径持续守护。
- **代价**：名义 floor 数字下降（88/81 → 78/69），需同步改写 `docs/CI_SSOT.md` 与
  workspace 规则中的宣称段落。
- **守卫**：`guard_coverage_floor.py` 检测到本次下调，以本 ADR（文件名含 coverage）
  放行；后续任何再下调仍需新 ADR。
