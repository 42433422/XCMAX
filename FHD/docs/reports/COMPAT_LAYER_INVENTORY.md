# Compat Layer Inventory

> Current state: application-layer `*_app_service_v2.py` dual track has been closed. This report no longer maintains V1/V2 pair inventory.

## Application Services

- `FHD/app/application/*_app_service_v2.py`: 0
- `app/application/app_service_pair_registry.py`: removed
- HTTP and planner code should use the existing no-suffix application service modules or the domain/route registry.

## Guard

- `tests/test_application/test_no_app_service_v2_files.py`
- `scripts/guard_no_new_v2_files.py`
- `scripts/ci/v2_versioned_py_allowlist.txt`

The allowlist is currently empty and must not contain `FHD/app/application/*_app_service_v2.py`.
