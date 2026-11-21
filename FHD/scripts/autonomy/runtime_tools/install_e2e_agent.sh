#!/usr/bin/env bash
# Compatibility installer: keep the historical destination and no-restart behavior.
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export DEVFLEET_PARA_MAIN_AGENT_DIR="${E2E_AGENT_DEST_DIR:-/Users/a4243342/XCMAX-runtime/para-main-agent}"
export DEVFLEET_PARA_MAIN_AGENT_RESTART=0
exec bash "$SCRIPT_DIR/install_para_e2e_agent.sh"
