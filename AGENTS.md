## Imported Claude Cowork project instructions

## Mandatory end-of-task cleanup

Before reporting a task complete:

1. Run `python3 scripts/dev/clean_agent_workspace.py` from the repository root.
2. Remove only temporary files, directories, and worktrees created by the current task after verifying they are no longer in use.
3. Preserve every pre-existing dirty change, active worktree, runtime data file, secret, and durable artifact. Never use `git clean -fdx`, broad recursive deletion, or `git add -A` as cleanup.
4. For large generated artifacts that may still be useful, move them to a recoverable archive and verify the copy before removing the source.
5. Include the cleanup result and remaining disk-space status in the final handoff. If cleanup cannot be completed safely, report the exact retained path and reason instead of silently leaving it behind.
