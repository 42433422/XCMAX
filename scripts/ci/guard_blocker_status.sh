#!/usr/bin/env bash
# guard_blocker_status.sh
# 用途：校验 2026-06 计划主 checklist 的 3 项阻塞（T36 / T37 / T59）仍保持 `[ ]`。
# 范围：specs/plan-2026-06-checklist.md
# 用法：bash scripts/ci/guard_blocker_status.sh
# 退出码：0 = 全部仍阻塞；1 = 至少 1 项被误标 [x]

set -euo pipefail

CHECKLIST="${1:-specs/plan-2026-06-checklist.md}"

if [[ ! -f "$CHECKLIST" ]]; then
  echo "[ERR] checklist not found: $CHECKLIST" >&2
  exit 2
fi

# 提取以 "- [x]/- [ ]" 开头且紧跟 T36/T37/T59 的行
check_status() {
  local task_id="$1"
  local line
  # 匹配 "- [x] T36：" / "- [ ] T36："（含中文冒号）
  line=$(grep -nE "^\\s*-\\s*\\[[ x]\\]\\s+${task_id}[:：]" "$CHECKLIST" | head -n1 || true)
  if [[ -z "$line" ]]; then
    echo "[ERR] 未找到 ${task_id} 的勾选行：$CHECKLIST" >&2
    return 1
  fi
  if echo "$line" | grep -qE "-\\s*\\[x\\]\\s+${task_id}"; then
    echo "[FAIL] ${task_id} 已被误标为 [x]（仍应阻塞）" >&2
    echo "       行：$line" >&2
    return 1
  fi
  echo "[OK] ${task_id} 仍阻塞 ([ ])"
  return 0
}

echo "[guard_blocker_status] 校验：$CHECKLIST"
fail=0
for tid in T36 T37 T59; do
  if ! check_status "$tid"; then
    fail=1
  fi
done

if [[ $fail -eq 0 ]]; then
  echo "[guard_blocker_status] 全部 3 项阻塞 (T36/T37/T59) 状态守卫通过"
  exit 0
else
  echo "[guard_blocker_status] 至少 1 项阻塞被误标，请参照 BLOCKERS.md 解封后再勾选" >&2
  exit 1
fi
