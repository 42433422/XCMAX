#!/usr/bin/env bash
set -euo pipefail

candidate="${1:-}"
release_sha="${2:-}"
target="/opt/prometheus/config/prometheus.yml"
archive_dir="/opt/prometheus/config/archive"
backup=""

fail() {
  printf 'production-prometheus: %s\n' "$*" >&2
  exit 1
}

restore_on_error() {
  status=$?
  if [[ "$status" -ne 0 && -n "$backup" && -f "$backup" ]]; then
    install -m 644 "$backup" "${target}.restore"
    mv -f "${target}.restore" "$target"
    docker kill --signal HUP prometheus >/dev/null 2>&1 || true
    printf 'production-prometheus: restored %s after failed rollout\n' "$backup" >&2
  fi
  exit "$status"
}
trap restore_on_error EXIT

[[ "$(id -u)" -eq 0 ]] || fail "root is required"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail "release SHA must contain 40 lowercase hex chars"
[[ -f "$candidate" ]] || fail "candidate config is missing"
[[ -f "$target" ]] || fail "current production config is missing"
for required in fhd-api-stable fhd-api-staging modstore-api-production; do
  grep -q "job_name: ${required}" "$candidate" || fail "missing scrape job ${required}"
done
[[ "$(grep -c 'environment: production' "$candidate")" -eq 2 ]] \
  || fail "exactly two production scrape targets are required"

image="$(docker inspect prometheus --format '{{.Config.Image}}')"
[[ -n "$image" ]] || fail "running Prometheus image is unavailable"
retention_args="$(docker inspect prometheus --format '{{join .Args " "}} {{join .Config.Cmd " "}}')"
case " $retention_args " in
  *"--storage.tsdb.retention.time=120d"*) ;;
  *) fail "Prometheus must retain raw metrics for the audited 120d window" ;;
esac
docker run --rm --entrypoint promtool \
  -v "${candidate}:/etc/prometheus/prometheus.yml:ro" \
  "$image" check config /etc/prometheus/prometheus.yml

install -d -m 700 "$archive_dir"
backup="${archive_dir}/prometheus.$(date -u +%Y%m%dT%H%M%SZ).${release_sha}.yml"
install -m 600 "$target" "$backup"
install -m 644 "$candidate" "${target}.next"
mv -f "${target}.next" "$target"
docker kill --signal HUP prometheus >/dev/null

python3 - <<'PY'
import json
import time
import urllib.request

expected = {
    "fhd-api-stable": "production",
    "fhd-api-staging": "staging",
    "modstore-api-production": "production",
}
deadline = time.monotonic() + 90
last = {}
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:9091/api/v1/targets", timeout=10
        ) as response:
            payload = json.load(response)
        last = {
            str(row.get("labels", {}).get("job") or ""): {
                "environment": str(row.get("labels", {}).get("environment") or ""),
                "health": str(row.get("health") or ""),
            }
            for row in payload.get("data", {}).get("activeTargets", [])
        }
        if all(
            last.get(job) == {"environment": environment, "health": "up"}
            for job, environment in expected.items()
        ):
            print(json.dumps({"ok": True, "targets": last}, sort_keys=True))
            break
    except (OSError, ValueError, TypeError):
        pass
    time.sleep(3)
else:
    raise SystemExit(json.dumps({"ok": False, "targets": last}, sort_keys=True))
PY

trap - EXIT
printf 'production-prometheus: installed release=%s backup=%s\n' "$release_sha" "$backup"
