#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TARGET_DIR="${DEVFLEET_PARA_MAIN_AGENT_DIR:-/Users/a4243342/XCMAX-runtime/para-main-agent}"
AGENT_SOURCE="$SCRIPT_DIR/para_e2e_agent.mjs"
HELPER_SOURCE="$SCRIPT_DIR/trae_failover.mjs"
QUEUE_POLICY_SOURCE="$SCRIPT_DIR/para_queue_policy.mjs"
RUNTIME_POLICY_SOURCE="$SCRIPT_DIR/e2e_agent_runtime_policy.mjs"
AGENT_TARGET="$TARGET_DIR/e2e-agent.mjs"
HELPER_TARGET="$TARGET_DIR/trae_failover.mjs"
QUEUE_POLICY_TARGET="$TARGET_DIR/para_queue_policy.mjs"
RUNTIME_POLICY_TARGET="$TARGET_DIR/e2e_agent_runtime_policy.mjs"
WATCHDOG_TARGET="$TARGET_DIR/run-watchdog.sh"
CONTROL_HELPERS=(tool_preflight.mjs control_receipt_outbox.mjs control_git_handoff.mjs credential_vault.mjs codex_model_gateway.mjs pushed_branch_pr.mjs)
LAUNCH_LABEL="${DEVFLEET_PARA_MAIN_AGENT_LABEL:-com.xcmax.para-main-agent.watchdog}"
BACKUP_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)-$$"

for source in "$AGENT_SOURCE" "$HELPER_SOURCE" "$QUEUE_POLICY_SOURCE" "$RUNTIME_POLICY_SOURCE"; do
  node --check "$source"
done
SNAPSHOT_TARGETS=("$AGENT_TARGET" "$HELPER_TARGET" "$QUEUE_POLICY_TARGET" "$RUNTIME_POLICY_TARGET")
for control_helper in "${CONTROL_HELPERS[@]}"; do
  node --check "$SCRIPT_DIR/$control_helper"
  SNAPSHOT_TARGETS+=("$TARGET_DIR/$control_helper")
done
if [[ -f "$WATCHDOG_TARGET" ]]; then
  bash -n "$WATCHDOG_TARGET"
  SNAPSHOT_TARGETS+=("$WATCHDOG_TARGET")
fi
node --test "$SCRIPT_DIR/e2e_agent_runtime_policy.test.mjs"
node --test "$SCRIPT_DIR/report_only_target_branch.test.mjs"
node --test "$SCRIPT_DIR/workspace_base_refresh.test.mjs"
mkdir -p "$TARGET_DIR"

# Snapshot every existing helper before any install can trigger rollback.
for target in "${SNAPSHOT_TARGETS[@]}"; do
  if [[ -f "$target" ]]; then cp -p "$target" "$target.backup-$BACKUP_SUFFIX"; fi
done

rollback() {
  for target in "${SNAPSHOT_TARGETS[@]}"; do
    if [[ -f "$target.backup-$BACKUP_SUFFIX" ]]; then
      cp -p "$target.backup-$BACKUP_SUFFIX" "$target"
    elif [[ -f "$target" ]]; then
      mv "$target" "$target.failed-install-$BACKUP_SUFFIX"
    fi
  done
}
trap rollback ERR

for control_helper in "${CONTROL_HELPERS[@]}"; do
  install -m 0644 "$SCRIPT_DIR/$control_helper" "$TARGET_DIR/$control_helper.next"
  mv "$TARGET_DIR/$control_helper.next" "$TARGET_DIR/$control_helper"
  cmp "$SCRIPT_DIR/$control_helper" "$TARGET_DIR/$control_helper"
done

if [[ -f "$WATCHDOG_TARGET.backup-$BACKUP_SUFFIX" ]]; then
  node - "$WATCHDOG_TARGET" "$WATCHDOG_TARGET.next" <<'JS'
const { accessSync, constants, readFileSync, statSync, writeFileSync } = require('node:fs');
const [target, next] = process.argv.slice(2);
let script = readFileSync(target, 'utf8').replace(
  /^([ \t]*)if \/usr\/sbin\/lsof -nP -iTCP:7890 -sTCP:LISTEN >\/dev\/null 2>&1; then$/m,
  '$1if /usr/bin/nc -z -G 2 127.0.0.1 7890 >/dev/null 2>&1; then');
const codex = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex';
let executable = false;
try { accessSync(codex, constants.X_OK); executable = true; } catch {}
if (executable) script = script.replace(/^([ \t]*DEVFLEET_CODEX_AGENT=)'\/Users\/a4243342\/\.local\/bin\/codex'([ \t]*\\)$/m, `$1'${codex}'$2`);
writeFileSync(next, script, { mode: statSync(target).mode & 0o777 });
JS
  bash -n "$WATCHDOG_TARGET.next"
  mv -f "$WATCHDOG_TARGET.next" "$WATCHDOG_TARGET"
fi

install -m 0755 "$AGENT_SOURCE" "$AGENT_TARGET.next"
install -m 0644 "$HELPER_SOURCE" "$HELPER_TARGET.next"
install -m 0644 "$QUEUE_POLICY_SOURCE" "$QUEUE_POLICY_TARGET.next"
install -m 0644 "$RUNTIME_POLICY_SOURCE" "$RUNTIME_POLICY_TARGET.next"
mv -f "$AGENT_TARGET.next" "$AGENT_TARGET"
mv -f "$HELPER_TARGET.next" "$HELPER_TARGET"
mv -f "$QUEUE_POLICY_TARGET.next" "$QUEUE_POLICY_TARGET"
mv -f "$RUNTIME_POLICY_TARGET.next" "$RUNTIME_POLICY_TARGET"

for target in "$AGENT_TARGET" "$HELPER_TARGET" "$QUEUE_POLICY_TARGET" "$RUNTIME_POLICY_TARGET"; do
  node --check "$target"
done
cmp "$AGENT_SOURCE" "$AGENT_TARGET"
cmp "$HELPER_SOURCE" "$HELPER_TARGET"
cmp "$QUEUE_POLICY_SOURCE" "$QUEUE_POLICY_TARGET"
cmp "$RUNTIME_POLICY_SOURCE" "$RUNTIME_POLICY_TARGET"

if [[ "${DEVFLEET_PARA_MAIN_AGENT_RESTART:-1}" != 0 ]]; then
  launchctl kickstart -k "gui/$(id -u)/$LAUNCH_LABEL"
  sleep 2
  launchctl print "gui/$(id -u)/$LAUNCH_LABEL" | grep -q 'state = running'
else
  printf 'installed_without_restart=1\n'
fi

trap - ERR
printf 'installed_agent_sha=%s\n' "$(shasum -a 256 "$AGENT_TARGET" | awk '{print $1}')"
printf 'installed_helper_sha=%s\n' "$(shasum -a 256 "$HELPER_TARGET" | awk '{print $1}')"
printf 'installed_queue_policy_sha=%s\n' "$(shasum -a 256 "$QUEUE_POLICY_TARGET" | awk '{print $1}')"
printf 'installed_runtime_policy_sha=%s\n' "$(shasum -a 256 "$RUNTIME_POLICY_TARGET" | awk '{print $1}')"
