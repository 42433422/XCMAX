#!/usr/bin/env bash
# Controlled alert acceptance on the production host (root):
#   bash run_alert_drill.sh <drill_id>
# Injects an unreachable `alert-drill` target (environment="drill", never part
# of the production SLO inventory), then records UTC timestamps for
# injected -> firing -> alertmanager_received -> notified -> handled ->
# resolved -> resolved_notified.  The drill target is always removed on exit.
set -euo pipefail

drill_id="${1:-}"
[[ "$drill_id" =~ ^[A-Za-z0-9._-]{4,64}$ ]] || { echo "invalid drill id" >&2; exit 1; }
sd_file="/opt/prometheus/config/file_sd/alert-drill-${drill_id}.json"
trap 'rm -f "$sd_file"' EXIT

SD_FILE="$sd_file" DRILL_ID="$drill_id" python3 - <<'PY'
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime

PROM, AM = "http://127.0.0.1:9091", "http://127.0.0.1:19093"
ALERT = "XcmaxControlledAlertDrill"
sd_file, drill_id = os.environ["SD_FILE"], os.environ["DRILL_ID"]
timeline: dict[str, str | None] = {}
result = {"schema": "xcagi.alert_drill/v1", "drill_id": drill_id, "timeline": timeline}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def webhook_counters() -> tuple[float, float]:
    with urllib.request.urlopen(f"{AM}/metrics", timeout=10) as response:
        text = response.read().decode()
    sent = failed = 0.0
    for line in text.splitlines():
        if 'integration="webhook"' not in line:
            continue
        if line.startswith("alertmanager_notifications_total"):
            sent += float(line.rsplit(" ", 1)[1])
        elif line.startswith("alertmanager_notifications_failed_total"):
            failed += float(line.rsplit(" ", 1)[1])
    return sent, failed


def prom_alert_state() -> str:
    for alert in get_json(f"{PROM}/api/v1/alerts")["data"]["alerts"]:
        labels = alert.get("labels", {})
        if labels.get("alertname") == ALERT and labels.get("drill_id") == drill_id:
            return str(alert.get("state"))
    return "inactive"


def am_has_alert() -> bool:
    query = urllib.parse.urlencode(
        [("filter", f'alertname="{ALERT}"'), ("filter", f'drill_id="{drill_id}"')]
    )
    return bool(get_json(f"{AM}/api/v2/alerts?{query}"))


def wait(step: str, predicate, timeout: float = 360) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                timeline[step] = now()
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(3)
    result["ok"] = False
    result["failed_step"] = step
    print(json.dumps(result, indent=2))
    raise SystemExit(1)


sent0, failed0 = webhook_counters()
target = [{"targets": ["127.0.0.1:9"], "labels": {"environment": "drill", "service": "drill", "drill_id": drill_id}}]
with open(sd_file, "w", encoding="utf-8") as handle:
    json.dump(target, handle)
timeline["injected"] = now()
wait("firing", lambda: prom_alert_state() == "firing")
wait("alertmanager_received", am_has_alert)
wait("notified", lambda: webhook_counters()[0] > sent0)
sent1, _ = webhook_counters()
os.remove(sd_file)
timeline["handled"] = now()
wait("resolved", lambda: prom_alert_state() == "inactive" and not am_has_alert())
wait("resolved_notified", lambda: webhook_counters()[0] > sent1)
failed_delta = webhook_counters()[1] - failed0
result["webhook_failures"] = failed_delta
result["ok"] = failed_delta == 0
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["ok"] else 1)
PY
