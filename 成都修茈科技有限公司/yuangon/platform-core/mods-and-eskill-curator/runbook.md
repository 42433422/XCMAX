# Runbook — Mods/ESkill 策展员

| 字段 | 值 |
|------|----|
| 员工 ID | `mods-and-eskill-curator` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 日常巡检

### 巡检 1：market_files/ 包状态检查

```bash
# 列出所有 .xcemp 包
ls MODstore_deploy/modstore_server/market_files/*.xcemp 2>/dev/null

# 检查 REGISTRY.json 完整性
python -c "
import json, os, glob
reg_path = 'MODstore_deploy/modstore_server/market_files/REGISTRY.json'
with open(reg_path) as f:
    reg = json.load(f)
reg_pkgs = {p['filename'] for p in reg.get('packages', [])}
disk_pkgs = set(glob.glob('MODstore_deploy/modstore_server/market_files/*.xcemp'))
disk_names = {os.path.basename(p) for p in disk_pkgs}
orphaned = disk_names - reg_pkgs
missing = reg_pkgs - disk_names
if orphaned:
    print(f'ORPHANED (disk but not in registry): {orphaned}')
if missing:
    print(f'MISSING (registry but not on disk): {missing}')
if not orphaned and not missing:
    print('REGISTRY.json consistency OK')
deprecated = [p['filename'] for p in reg.get('packages', []) if p.get('deprecated')]
if deprecated:
    print(f'DEPRECATED packages: {deprecated}')
pending = [p['filename'] for p in reg.get('packages', []) if p.get('review_status') == 'pending']
if pending:
    print(f'PENDING review: {len(pending)} packages')
"
```

### 巡检 2：mods/ 目录结构检查

```bash
# 列出所有 Mod 包
ls mods/

# 校验每个 manifest.json 是否符合 schema
python -c "
import json, os, glob
schema_path = 'mods/manifest-schema.json'
with open(schema_path) as f:
    schema = json.load(f)
required = schema.get('required', [])
for mf in glob.glob('mods/*/manifest.json'):
    with open(mf) as f:
        manifest = json.load(f)
    missing = [r for r in required if r not in manifest]
    if missing:
        print(f'SCHEMA FAIL {mf}: missing {missing}')
    else:
        print(f'SCHEMA OK {mf}')
"
```

### 巡检 3：eskill-prototype/ 目录检查

```bash
# 检查原型实验目录
ls eskill-prototype/experiments/ 2>/dev/null || echo 'No experiments yet'

# 检查是否有已推进但未清理的原型
find eskill-prototype/experiments/ -name 'promoted.flag' 2>/dev/null
```

### 巡检 4：ESkill.md 格式检查

```bash
python -c "
with open('ESkill.md') as f:
    content = f.read()
checks = [
    ('## 3. 四阶段生命周期', '四阶段生命周期章节'),
    ('## 7. 双层进化架构', '双层进化架构章节'),
    ('## 10. 文档变更记录', '变更记录章节'),
]
for pattern, desc in checks:
    if pattern in content:
        print(f'OK: {desc}')
    else:
        print(f'MISSING: {desc}')
"
```

### 巡检 5：ESkill.md 与实现一致性

```bash
# 检查 ESkill.md 引用的类是否在 eskill_runtime.py 中存在
python -c "
with open('ESkill.md') as f:
    doc = f.read()
with open('MODstore_deploy/modstore_server/eskill_runtime.py') as f:
    code = f.read()
classes_in_code = ['ESkillRuntime', 'RuleBasedESkillAdapter']
for cls in classes_in_code:
    if cls in code:
        print(f'IMPL OK: {cls}')
    else:
        print(f'IMPL MISSING: {cls}')
"
```

## 异常处置

### 异常 1：.xcemp 包 schema 不合法

**排查**：用 `employee_pack_export.py --validate` 检查包结构。
**修复**：退回给开发员工补全必填字段；重新审核。

### 异常 2：废弃包未清理导致目录混乱

**排查**：运行巡检 1，检查 REGISTRY.json 中 `deprecated=true` 的包。
**修复**：
1. 标记废弃包（文件名追加 `.deprecated`）
2. 更新 REGISTRY.json 中的 `deprecated` 字段为 `true`
3. 通知 `employee-pack-curator` 更新注册表

### 异常 3：ESkill.md 与实现不一致

**排查**：运行巡检 5，对比文档引用与代码实现。
**修复**：
1. 更新 `ESkill.md` 对应章节
2. 在 §10 变更记录中追加本次同步记录
3. 通知 `doc-knowledge-curator` 同步文档库

### 异常 4：REGISTRY.json 不存在或格式损坏

**排查**：检查 `MODstore_deploy/modstore_server/market_files/REGISTRY.json` 是否存在且可解析。
**修复**：
1. 若文件不存在，扫描 `market_files/*.xcemp` 重新生成初始 REGISTRY.json
2. 若格式损坏，尝试从备份恢复或重新生成
3. 所有包的 `review_status` 设为 `pending`

### 异常 5：孤儿包（磁盘有文件但 REGISTRY.json 无记录）

**排查**：运行巡检 1，检查 `orphaned` 输出。
**修复**：
1. 确认孤儿包是否为合法包
2. 若合法，在 REGISTRY.json 中补全记录
3. 若不合法或来源不明，标记 `.deprecated` 并更新 REGISTRY.json

### 异常 6：原型推进失败

**排查**：检查 `eskill-prototype/experiments/<id>/results/` 下的实验结果。
**修复**：
1. 分析失败原因（逻辑类型不支持、secret 泄露、质量不达标等）
2. 生成修复建议返回给开发员工
3. 若多次失败，标记实验为 `abandoned`

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
