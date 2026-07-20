#!/usr/bin/env bash
# shellcheck shell=bash

verify_release_identity_payload() {
  local payload="$1"
  local expected_git_sha="$2"
  local expected_image_digest="${3:-}"
  local expected_artifact_sha256="${4:-}"

  if [[ -z "$expected_git_sha" ]]; then
    echo "[identity] expected git SHA is required" >&2
    return 1
  fi
  HEALTH_PAYLOAD="$payload" EXPECTED_GIT_SHA="$expected_git_sha" \
    EXPECTED_IMAGE_DIGEST="$expected_image_digest" \
    EXPECTED_ARTIFACT_SHA256="$expected_artifact_sha256" python3 - <<'PY'
import json
import os
import sys

try:
    payload = json.loads(os.environ["HEALTH_PAYLOAD"])
except (KeyError, json.JSONDecodeError) as exc:
    print(f"[identity] invalid health JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)

build = payload.get("build") if isinstance(payload.get("build"), dict) else payload
actual_sha = str(build.get("git_sha") or "")
actual_digest = str(build.get("image_digest") or "")
actual_artifact = str(build.get("artifact_sha256") or "")
expected_sha = os.environ["EXPECTED_GIT_SHA"]
expected_digest = os.environ.get("EXPECTED_IMAGE_DIGEST", "")
expected_artifact = os.environ.get("EXPECTED_ARTIFACT_SHA256", "")
if actual_sha != expected_sha:
    print(
        f"[identity] git SHA mismatch expected={expected_sha} actual={actual_sha or '<missing>'}",
        file=sys.stderr,
    )
    raise SystemExit(1)
if expected_digest and actual_digest != expected_digest:
    print(
        f"[identity] image digest mismatch expected={expected_digest} actual={actual_digest or '<missing>'}",
        file=sys.stderr,
    )
    raise SystemExit(1)
if expected_artifact and actual_artifact != expected_artifact:
    print(
        f"[identity] artifact SHA256 mismatch expected={expected_artifact} actual={actual_artifact or '<missing>'}",
        file=sys.stderr,
    )
    raise SystemExit(1)
print(json.dumps({"artifact_sha256": actual_artifact, "git_sha": actual_sha, "image_digest": actual_digest}, sort_keys=True))
PY
}

verify_release_health_identity() {
  local health_url="$1"
  local expected_git_sha="$2"
  local expected_image_digest="${3:-}"
  local expected_artifact_sha256="${4:-}"
  local payload

  payload="$(curl --noproxy '*' -fsS --max-time 8 "$health_url")" || return 1
  verify_release_identity_payload \
    "$payload" "$expected_git_sha" "$expected_image_digest" "$expected_artifact_sha256"
}
