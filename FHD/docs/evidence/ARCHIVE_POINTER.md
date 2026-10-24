# FHD/docs/evidence media archive pointer

2026-10-25: binary media (png/jpg/webm/mp4/...) removed from the git tree.

| item | value |
|----|----|
| archive | `~/XCMAX-archives/evidence-bulk-20261025/` |
| manifest | `MANIFEST.json` / `MANIFEST.txt` (sha256 per file) |
| kept in git | `.json` / `.md` / `.py` / `.log` / `.txt` text evidence |

Restore example:

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/evidence-bulk-20261025"
rsync -a --relative "$AR/./FHD/docs/evidence/e2e/" "$(pwd)/"
```

Capability-center public evidence is served via COS presigned URLs; local copies are no longer required in-repo.
