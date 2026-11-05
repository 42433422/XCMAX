#!/usr/bin/env bash
# Run on the production host (as root, usually via `ssh host 'bash -s' < this`).
# Diagnoses the hand-provisioned `prometheus` container, starts it if it was
# left stopped, enforces a restart policy, and waits for the host-local query
# API.  It never recreates the container, so the 120d TSDB volume is untouched.
set -euo pipefail

container="${PROMETHEUS_CONTAINER:-prometheus}"
url="${PROMETHEUS_LOCAL_URL:-http://127.0.0.1:9091}"
actions=()

state_json() {
  docker inspect "$container" --format \
    '{"status":"{{.State.Status}}","exit_code":{{.State.ExitCode}},"oom_killed":{{.State.OOMKilled}},"restart_count":{{.RestartCount}},"started_at":"{{.State.StartedAt}}","finished_at":"{{.State.FinishedAt}}","restart_policy":"{{.HostConfig.RestartPolicy.Name}}","network_mode":"{{.HostConfig.NetworkMode}}"}'
}

if ! docker inspect "$container" >/dev/null 2>&1; then
  printf '{"ok":false,"container":"%s","error":"container_missing"}\n' "$container"
  exit 1
fi
before="$(state_json)"
case " $(docker inspect "$container" --format '{{join .Args " "}} {{join .Config.Cmd " "}}') " in
  *"--storage.tsdb.retention.time=120d"*) retention_ok=true ;;
  *) retention_ok=false ;;
esac
if [[ "$(docker inspect "$container" --format '{{.HostConfig.RestartPolicy.Name}}')" =~ ^(|no)$ ]]; then
  docker update --restart unless-stopped "$container" >/dev/null
  actions+=("restart_policy:unless-stopped")
fi
if [[ "$(docker inspect "$container" --format '{{.State.Running}}')" != "true" ]]; then
  docker start "$container" >/dev/null
  actions+=("started")
fi

ready=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "${url}/-/ready" >/dev/null 2>&1 \
    && curl -fsS --max-time 10 -G --data-urlencode 'query=vector(1)' "${url}/api/v1/query" \
      | grep -q '"status":"success"'; then
    ready=true
    break
  fi
  sleep 3
done
listening="$(ss -ltnH "( sport = :${url##*:} )" 2>/dev/null | awk '{print $4}' | paste -sd, -)"
printf '{"ok":%s,"container":"%s","url":"%s","listening":"%s","retention_120d":%s,"actions":"%s","before":%s,"after":%s}\n' \
  "$([[ "$ready" == true && "$retention_ok" == true ]] && echo true || echo false)" \
  "$container" "$url" "$listening" "$retention_ok" "${actions[*]:-}" "$before" "$(state_json)"
if [[ "$ready" != true || "$retention_ok" != true ]]; then
  docker logs --tail 40 "$container" >&2 2>&1 || true
  exit 1
fi
