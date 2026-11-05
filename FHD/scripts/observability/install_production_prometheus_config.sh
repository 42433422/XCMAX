#!/usr/bin/env bash
# Usage: install_production_prometheus_config.sh <bundle_dir> <release_sha>
# bundle_dir holds prometheus.production.yml, production-alerts.yml,
# alertmanager.production.yml and ensure_production_prometheus.sh.
# OPS_ALERT_WEBHOOK_URL (env) is the ops channel receiving Alertmanager webhooks.
set -euo pipefail

bundle="${1:-}"
release_sha="${2:-}"
config_dir="/opt/prometheus/config"
target="${config_dir}/prometheus.yml"
rules="${config_dir}/production-alerts.yml"
archive_dir="${config_dir}/archive"
am_dir="/opt/xcmax-alertmanager"
am_container="xcmax-alertmanager"
am_image="prom/alertmanager:v0.27.0"
am_url="http://127.0.0.1:19093"
backup=""
rules_backup=""

fail() {
  printf 'production-prometheus: %s\n' "$*" >&2
  exit 1
}

restore_on_error() {
  status=$?
  if [[ "$status" -ne 0 && -n "$backup" && -f "$backup" ]]; then
    install -m 644 "$backup" "${target}.restore"
    mv -f "${target}.restore" "$target"
    if [[ -n "$rules_backup" && -f "$rules_backup" ]]; then
      install -m 644 "$rules_backup" "$rules"
    fi
    docker kill --signal HUP prometheus >/dev/null 2>&1 || true
    printf 'production-prometheus: restored %s after failed rollout\n' "$backup" >&2
  fi
  exit "$status"
}
trap restore_on_error EXIT

[[ "$(id -u)" -eq 0 ]] || fail "root is required"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail "release SHA must contain 40 lowercase hex chars"
for file in prometheus.production.yml production-alerts.yml alertmanager.production.yml ensure_production_prometheus.sh; do
  [[ -f "${bundle}/${file}" ]] || fail "bundle file ${file} is missing"
done
[[ -f "$target" ]] || fail "current production config is missing"
[[ "${OPS_ALERT_WEBHOOK_URL:-}" =~ ^https:// ]] || fail "OPS_ALERT_WEBHOOK_URL must be an https ops channel"
candidate="${bundle}/prometheus.production.yml"
for required in fhd-api-stable fhd-api-staging modstore-api-production; do
  grep -q "job_name: ${required}" "$candidate" || fail "missing scrape job ${required}"
done
[[ "$(grep -c 'environment: production' "$candidate")" -eq 2 ]] \
  || fail "exactly two production scrape targets are required"

# Also enforces --storage.tsdb.retention.time=120d and a restart policy.
bash "${bundle}/ensure_production_prometheus.sh"

image="$(docker inspect prometheus --format '{{.Config.Image}}')"
staging="$(mktemp -d)"
install -d "${staging}/file_sd"
install -m 644 "$candidate" "${staging}/prometheus.yml"
install -m 644 "${bundle}/production-alerts.yml" "${staging}/production-alerts.yml"
docker run --rm --entrypoint promtool -v "${staging}:/etc/prometheus:ro" \
  "$image" check config /etc/prometheus/prometheus.yml

install -d -m 755 "${am_dir}" "${am_dir}/secrets"
chmod 700 "${am_dir}/secrets"
printf '%s' "$OPS_ALERT_WEBHOOK_URL" > "${am_dir}/secrets/ops_webhook_url.next"
chmod 600 "${am_dir}/secrets/ops_webhook_url.next"
mv -f "${am_dir}/secrets/ops_webhook_url.next" "${am_dir}/secrets/ops_webhook_url"
install -m 644 "${bundle}/alertmanager.production.yml" "${am_dir}/alertmanager.yml.next"
docker run --rm --entrypoint amtool -v "${am_dir}:/etc/alertmanager:ro" "$am_image" \
  check-config /etc/alertmanager/alertmanager.yml.next
mv -f "${am_dir}/alertmanager.yml.next" "${am_dir}/alertmanager.yml"
if docker inspect "$am_container" >/dev/null 2>&1; then
  docker start "$am_container" >/dev/null
  docker kill --signal HUP "$am_container" >/dev/null
else
  docker run -d --name "$am_container" --restart unless-stopped --network host \
    -v "${am_dir}:/etc/alertmanager:ro" -v xcmax-alertmanager-data:/alertmanager \
    "$am_image" --config.file=/etc/alertmanager/alertmanager.yml \
    --storage.path=/alertmanager --web.listen-address=127.0.0.1:19093 \
    --cluster.listen-address= >/dev/null
fi

install -d -m 700 "$archive_dir"
install -d -m 755 "${config_dir}/file_sd"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="${archive_dir}/prometheus.${stamp}.${release_sha}.yml"
install -m 600 "$target" "$backup"
if [[ -f "$rules" ]]; then
  rules_backup="${archive_dir}/production-alerts.${stamp}.${release_sha}.yml"
  install -m 600 "$rules" "$rules_backup"
fi
install -m 644 "${staging}/production-alerts.yml" "$rules"
install -m 644 "$candidate" "${target}.next"
mv -f "${target}.next" "$target"
rm -rf "$staging"
docker kill --signal HUP prometheus >/dev/null

PROM_URL="http://127.0.0.1:9091" AM_URL="$am_url" python3 - <<'PY'
import json
import os
import time
import urllib.request

prom, am = os.environ["PROM_URL"], os.environ["AM_URL"]
expected = {
    "fhd-api-stable": ("production", "fhd"),
    "fhd-api-staging": ("staging", "fhd"),
    "modstore-api-production": ("production", "modstore"),
}
groups = {"xcmax_production_scrape", "xcmax_production_slo", "xcmax_alert_drill"}


def get(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


deadline = time.monotonic() + 90
last: dict = {}
while time.monotonic() < deadline:
    try:
        targets = {
            str(row["labels"].get("job")): {
                "environment": row["labels"].get("environment"),
                "service": row["labels"].get("service"),
                "health": row.get("health"),
            }
            for row in get(f"{prom}/api/v1/targets")["data"]["activeTargets"]
        }
        loaded = {g["name"] for g in get(f"{prom}/api/v1/rules")["data"]["groups"]}
        managers = [
            row.get("url", "")
            for row in get(f"{prom}/api/v1/alertmanagers")["data"]["activeAlertmanagers"]
        ]
        receivers = {r["name"] for r in get(f"{am}/api/v2/receivers")}
        last = {
            "targets": targets,
            "rule_groups": sorted(loaded),
            "alertmanagers": managers,
            "receivers": sorted(receivers),
        }
        if (
            all(
                targets.get(job) == {"environment": env, "service": svc, "health": "up"}
                for job, (env, svc) in expected.items()
            )
            and groups <= loaded
            and any("127.0.0.1:19093" in url for url in managers)
            and "ops-webhook" in receivers
        ):
            print(json.dumps({"ok": True, **last}, sort_keys=True))
            break
    except (OSError, ValueError, TypeError, KeyError):
        pass
    time.sleep(3)
else:
    raise SystemExit(json.dumps({"ok": False, **last}, sort_keys=True))
PY

trap - EXIT
printf 'production-prometheus: installed release=%s backup=%s\n' "$release_sha" "$backup"
