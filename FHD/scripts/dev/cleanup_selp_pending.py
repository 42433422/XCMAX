"""清理自演化循环遗留的 pending open_items。"""
import json
import os
import datetime

PATHS = [
    os.path.expanduser(
        "~/Library/Application Support/XCMAX/modstore-daily/runtime/"
        "self_maintenance_loop_memory.json"
    ),
    os.path.expanduser(
        "~/.xcmax/modstore-daily/self_maintenance_loop_memory.json"
    ),
]

now = datetime.datetime.now(datetime.timezone.utc).isoformat()

for path in PATHS:
    if not os.path.exists(path):
        print(f"SKIP (not found): {path}")
        continue

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    open_items = data.get("open_items", [])
    closed = data.get("closed_items", [])

    if not open_items:
        print(f"SKIP (already clean): {path}")
        continue

    for item in open_items:
        item["actor"] = "manual_cleanup"
        item["closed_at"] = now
        item["resolution_reason"] = "manually_resolved_by_operator_stale_llm_failure"
        closed.append(item)

    data["open_items"] = []
    data["closed_items"] = closed[-200:]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"CLEANED: {path}")
    print(f"  moved {len(open_items)} items -> closed_items")
    print(f"  open_items=0  closed_items={len(data['closed_items'])}")

print("\nDone.")
