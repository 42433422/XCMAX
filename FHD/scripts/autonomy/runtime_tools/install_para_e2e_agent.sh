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
LAUNCH_LABEL="${DEVFLEET_PARA_MAIN_AGENT_LABEL:-com.xcmax.para-main-agent.watchdog}"
BACKUP_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)"

node --check "$AGENT_SOURCE"
node --check "$HELPER_SOURCE"
node --check "$QUEUE_POLICY_SOURCE"
node --check "$RUNTIME_POLICY_SOURCE"
node --test "$SCRIPT_DIR/e2e_agent_runtime_policy.test.mjs"
node --test "$SCRIPT_DIR/report_only_target_branch.test.mjs"
node --test "$SCRIPT_DIR/workspace_base_refresh.test.mjs"
mkdir -p "$TARGET_DIR"

AGENT_BACKUP=""
HELPER_BACKUP=""
QUEUE_POLICY_BACKUP=""
RUNTIME_POLICY_BACKUP=""
AGENT_EXISTED=0
HELPER_EXISTED=0
QUEUE_POLICY_EXISTED=0
RUNTIME_POLICY_EXISTED=0
if [[ -f "$AGENT_TARGET" ]]; then
  AGENT_EXISTED=1
  AGENT_BACKUP="$AGENT_TARGET.backup-$BACKUP_SUFFIX"
  cp -p "$AGENT_TARGET" "$AGENT_BACKUP"
fi
if [[ -f "$HELPER_TARGET" ]]; then
  HELPER_EXISTED=1
  HELPER_BACKUP="$HELPER_TARGET.backup-$BACKUP_SUFFIX"
  cp -p "$HELPER_TARGET" "$HELPER_BACKUP"
fi
if [[ -f "$QUEUE_POLICY_TARGET" ]]; then
  QUEUE_POLICY_EXISTED=1
  QUEUE_POLICY_BACKUP="$QUEUE_POLICY_TARGET.backup-$BACKUP_SUFFIX"
  cp -p "$QUEUE_POLICY_TARGET" "$QUEUE_POLICY_BACKUP"
fi
if [[ -f "$RUNTIME_POLICY_TARGET" ]]; then
  RUNTIME_POLICY_EXISTED=1
  RUNTIME_POLICY_BACKUP="$RUNTIME_POLICY_TARGET.backup-$BACKUP_SUFFIX"
  cp -p "$RUNTIME_POLICY_TARGET" "$RUNTIME_POLICY_BACKUP"
fi

rollback() {
  if [[ -n "$AGENT_BACKUP" && -f "$AGENT_BACKUP" ]]; then cp -p "$AGENT_BACKUP" "$AGENT_TARGET"; fi
  if [[ -n "$HELPER_BACKUP" && -f "$HELPER_BACKUP" ]]; then cp -p "$HELPER_BACKUP" "$HELPER_TARGET"; fi
  if [[ -n "$QUEUE_POLICY_BACKUP" && -f "$QUEUE_POLICY_BACKUP" ]]; then cp -p "$QUEUE_POLICY_BACKUP" "$QUEUE_POLICY_TARGET"; fi
  if [[ -n "$RUNTIME_POLICY_BACKUP" && -f "$RUNTIME_POLICY_BACKUP" ]]; then cp -p "$RUNTIME_POLICY_BACKUP" "$RUNTIME_POLICY_TARGET"; fi
  if [[ "$AGENT_EXISTED" == 0 && -f "$AGENT_TARGET" ]]; then
    mv -f "$AGENT_TARGET" "$AGENT_TARGET.failed-install-$BACKUP_SUFFIX"
  fi
  if [[ "$HELPER_EXISTED" == 0 && -f "$HELPER_TARGET" ]]; then
    mv -f "$HELPER_TARGET" "$HELPER_TARGET.failed-install-$BACKUP_SUFFIX"
  fi
  if [[ "$QUEUE_POLICY_EXISTED" == 0 && -f "$QUEUE_POLICY_TARGET" ]]; then
    mv -f "$QUEUE_POLICY_TARGET" "$QUEUE_POLICY_TARGET.failed-install-$BACKUP_SUFFIX"
  fi
  if [[ "$RUNTIME_POLICY_EXISTED" == 0 && -f "$RUNTIME_POLICY_TARGET" ]]; then
    mv -f "$RUNTIME_POLICY_TARGET" "$RUNTIME_POLICY_TARGET.failed-install-$BACKUP_SUFFIX"
  fi
}
trap rollback ERR

install -m 0755 "$AGENT_SOURCE" "$AGENT_TARGET.next"
install -m 0644 "$HELPER_SOURCE" "$HELPER_TARGET.next"
install -m 0644 "$QUEUE_POLICY_SOURCE" "$QUEUE_POLICY_TARGET.next"
install -m 0644 "$RUNTIME_POLICY_SOURCE" "$RUNTIME_POLICY_TARGET.next"
mv -f "$AGENT_TARGET.next" "$AGENT_TARGET"
mv -f "$HELPER_TARGET.next" "$HELPER_TARGET"
mv -f "$QUEUE_POLICY_TARGET.next" "$QUEUE_POLICY_TARGET"
mv -f "$RUNTIME_POLICY_TARGET.next" "$RUNTIME_POLICY_TARGET"

node --check "$AGENT_TARGET"
node --check "$HELPER_TARGET"
node --check "$QUEUE_POLICY_TARGET"
node --check "$RUNTIME_POLICY_TARGET"
[[ "$(shasum -a 256 "$AGENT_SOURCE" | awk '{print $1}')" == "$(shasum -a 256 "$AGENT_TARGET" | awk '{print $1}')" ]]
[[ "$(shasum -a 256 "$HELPER_SOURCE" | awk '{print $1}')" == "$(shasum -a 256 "$HELPER_TARGET" | awk '{print $1}')" ]]
[[ "$(shasum -a 256 "$QUEUE_POLICY_SOURCE" | awk '{print $1}')" == "$(shasum -a 256 "$QUEUE_POLICY_TARGET" | awk '{print $1}')" ]]
[[ "$(shasum -a 256 "$RUNTIME_POLICY_SOURCE" | awk '{print $1}')" == "$(shasum -a 256 "$RUNTIME_POLICY_TARGET" | awk '{print $1}')" ]]

if [[ "${DEVFLEET_PARA_MAIN_AGENT_RESTART:-1}" == 0 ]]; then
  trap - ERR
  printf 'installed_without_restart=1\n'
  printf 'installed_agent_sha=%s\n' "$(shasum -a 256 "$AGENT_TARGET" | awk '{print $1}')"
  printf 'installed_helper_sha=%s\n' "$(shasum -a 256 "$HELPER_TARGET" | awk '{print $1}')"
  printf 'installed_queue_policy_sha=%s\n' "$(shasum -a 256 "$QUEUE_POLICY_TARGET" | awk '{print $1}')"
  printf 'installed_runtime_policy_sha=%s\n' "$(shasum -a 256 "$RUNTIME_POLICY_TARGET" | awk '{print $1}')"
  exit 0
fi

launchctl kickstart -k "gui/$(id -u)/$LAUNCH_LABEL"
sleep 2
launchctl print "gui/$(id -u)/$LAUNCH_LABEL" | grep -q 'state = running'

trap - ERR
printf 'installed_agent_sha=%s\n' "$(shasum -a 256 "$AGENT_TARGET" | awk '{print $1}')"
printf 'installed_helper_sha=%s\n' "$(shasum -a 256 "$HELPER_TARGET" | awk '{print $1}')"
printf 'installed_queue_policy_sha=%s\n' "$(shasum -a 256 "$QUEUE_POLICY_TARGET" | awk '{print $1}')"
printf 'installed_runtime_policy_sha=%s\n' "$(shasum -a 256 "$RUNTIME_POLICY_TARGET" | awk '{print $1}')"
