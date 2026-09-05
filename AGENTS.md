## Imported Claude Cowork project instructions

## Product mainline and delivery

`origin/main` is the shared product baseline. For product implementation and delivery requests:

Customer customization belongs in versioned Mods with account-scoped entitlement and data ownership. All customers use the shared host built from `main`; do not maintain customer-specific host branches or installers containing a divergent product runtime. A short-lived review branch is not a customer delivery channel. Verify that a shared host update preserves and can update the customer's authorized Mods.

1. Before editing, inspect the current checkout, active worktrees, and relevant prior feature commits. Preserve existing work. If a user says an earlier feature disappeared, trace its commit and actual mainline inclusion instead of reimplementing an older design.
2. Use one integration PR for the active product delivery. Track required historical changes as included, adapted with a replacement commit, or explicitly outstanding. Do not merge unrelated dependency upgrades or other agents' unfinished work merely to unify branches.
3. Passing local tests or building a branch candidate is intermediate progress. Complete the required checks and merge the authorized product change into `main` before describing it as integrated or delivered. Never bypass branch protection. If a check or external dependency prevents merging, report the exact pending condition and keep the work identifiable.
4. Build the delivery artifact from an exact commit already present on `origin/main`. Verify the artifact's `build-info`, running backend identity, and visible UI against that same commit. Label branch builds as acceptance candidates; do not substitute them for the installed or published product.
5. Before handoff, report the integration PR, mainline commit, tested artifact or installed identity, and any remaining mismatch. Preserve active worktrees and uncommitted changes when refreshing the local checkout.

Read-only reviews, design proposals, and requests explicitly limited to a draft do not require merging or releasing.

## Mandatory end-of-task cleanup

Before reporting a task complete:

1. Run `python3 scripts/dev/clean_agent_workspace.py` from the repository root.
2. Remove only temporary files, directories, and worktrees created by the current task after verifying they are no longer in use.
3. Preserve every pre-existing dirty change, active worktree, runtime data file, secret, and durable artifact. Never use `git clean -fdx`, broad recursive deletion, or `git add -A` as cleanup.
4. For large generated artifacts that may still be useful, move them to a recoverable archive and verify the copy before removing the source.
5. Include the cleanup result and remaining disk-space status in the final handoff. If cleanup cannot be completed safely, report the exact retained path and reason instead of silently leaving it behind.
