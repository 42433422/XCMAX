#!/usr/bin/env bash
# M0 · GitHub branch protection: require release-gate jobs (no secrets)
# Run from a clone with gh authenticated: bash scripts/m0-github-branch-protection.sh [owner/repo]
set -euo pipefail

if ! command -v gh >/dev/null 2>&1; then
  echo "[skip] gh CLI not installed. Install: brew install gh && gh auth login"
  exit 0
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "[skip] gh not logged in. Run: gh auth login"
  exit 0
fi

REPO_SLUG="${1:-}"
if [[ -z "$REPO_SLUG" ]]; then
  if git remote get-url origin >/dev/null 2>&1; then
    REPO_SLUG="$(git remote get-url origin | sed -E 's#.*github\.com[:/]([^/]+/[^/.]+)(\.git)?#\1#')"
  fi
fi
if [[ -z "$REPO_SLUG" ]]; then
  echo "[err] Pass owner/repo or run inside a git repo with github.com origin"
  exit 1
fi

OWNER="${REPO_SLUG%%/*}"
REPO="${REPO_SLUG##*/}"
BRANCH="${M0_PROTECT_BRANCH:-main}"
for try in main master; do
  if gh api -q .name "repos/${OWNER}/${REPO}/branches/${try}" >/dev/null 2>&1; then
    BRANCH="$try"
    break
  fi
done

echo "=== M0 branch protection ==="
echo "repo=${OWNER}/${REPO} branch=${BRANCH}"

echo ""
echo "--- Current protection (if any) ---"
gh api "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" 2>/dev/null \
  | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
except Exception:
  print('(none or no admin access)')
  sys.exit(0)
ctx=d.get('required_status_checks') or {}
print('strict:', ctx.get('strict'))
print('contexts:', ctx.get('contexts'))
" || echo "(not protected or insufficient scope)"

# Status check contexts: workflow job `name` on GitHub (verify via check-runs below)
case "${REPO}" in
  ai-excel-helper)
    CONTEXTS=(
      "Release gate (hard block)"
      "XCAGI CI/CD / Release gate (hard block)"
    )
    ;;
  XCai)
    # release-gate is a step inside this job on github.com/42433422/XCai (not a separate check)
    CONTEXTS=(
      "MODstore (Python — lint + tests + coverage)"
      "CI - Backend Python / MODstore (Python — lint + tests + coverage)"
    )
    ;;
  *)
    CONTEXTS=(
      "Release gate (hard block)"
      "MODstore (Python — lint + tests + coverage)"
    )
    ;;
esac

echo ""
echo "--- Applying required status checks (idempotent merge) ---"
CTX_JSON="$(printf '%s\n' "${CONTEXTS[@]}" | python3 -c "
import json,sys
seen=set()
out=[]
for line in sys.stdin:
    c=line.strip()
    if c and c not in seen:
        seen.add(c)
        out.append(c)
print(json.dumps(out))
")"
payload="$(python3 -c "
import json,sys
contexts=json.loads(sys.argv[1])
print(json.dumps({
  'required_status_checks': {'strict': True, 'contexts': contexts},
  'enforce_admins': False,
  'required_pull_request_reviews': None,
  'restrictions': None,
  'required_linear_history': False,
  'allow_force_pushes': False,
  'allow_deletions': False,
  'block_creations': False,
  'required_conversation_resolution': False,
}))
" "$CTX_JSON")"

if gh api -X PUT "repos/${OWNER}/${REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - <<<"$payload" >/dev/null 2>&1; then
  echo "[ok] protection updated for ${BRANCH}"
else
  echo "[warn] PUT protection failed — try UI: Settings → Branches → ${BRANCH}"
  echo "       Required checks to add manually:"
  printf '         - %s\n' "${CONTEXTS[@]}"
  echo ""
  echo "Alternative (classic contexts only):"
  echo "  gh api --method PUT repos/${OWNER}/${REPO}/branches/${BRANCH}/protection \\"
  echo "    -f required_status_checks[strict]=true \\"
  echo "    -f required_status_checks[contexts][]='Release gate (hard block)' \\"
  echo "    -f required_status_checks[contexts][]='release-gate'"
fi

echo ""
echo "--- List recent check runs (discover exact context names) ---"
gh api "repos/${OWNER}/${REPO}/commits/${BRANCH}" -q '.sha' 2>/dev/null | head -1 | while read -r sha; do
  [[ -n "$sha" ]] || continue
  gh api "repos/${OWNER}/${REPO}/commits/${sha}/check-runs" -q '.check_runs[] | "\(.name) → \(.status) \(.conclusion // "")"' 2>/dev/null | head -20 || true
done
