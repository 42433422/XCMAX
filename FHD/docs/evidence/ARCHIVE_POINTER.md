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


## Round 2 — 2026-10-25 (debt24 closeout)

Additional tracked media removed from the git tree after independent `git ls-tree` showed
~407 MiB still under `FHD/docs/evidence/` post-#2627.

| item | value |
|------|-------|
| archive | `~/XCMAX-archives/evidence-bulk-20261025-round2/` |
| manifest | `MANIFEST.json` / `MANIFEST.txt` (sha256 per file) |
| removed | 930 media/binary files ≈ 394.62 MiB |
| kept in git | `.json` / `.md` / `.py` / `.log` / `.txt` text evidence |

Verify tree size after this change:

```bash
git ls-tree -r -l HEAD -- FHD/docs/evidence/ | awk '{s+=$4} END{printf "evidence MiB=%.2f\n", s/1024/1024}'
git ls-tree -r -l HEAD | awk '{s+=$4} END{printf "tree MiB=%.2f\n", s/1024/1024}'
```

Do **not** claim a size that has not been re-measured with the commands above.


## Archive-backed verification (debt24)

`成都修茈科技有限公司/scripts/evidence_assets.py check` accepts originals that are
**absent from the git tree** when their `sha256`+size match a local
`~/XCMAX-archives/evidence-bulk-*/MANIFEST.json` entry (or `$XCMAX_ARCHIVE_ROOT`).

CI runners that lack the archive mounts must either:
1. restore required batches before `check`, or
2. rely on the same archive root available to the job.

Capability-center public assets remain COS-served; local git copies are not required
for every historical acceptance video.


Committed MANIFEST copies (no blobs): `FHD/docs/evidence/archives/evidence-bulk-*/MANIFEST.json` — CI uses these when `~/XCMAX-archives` is absent.
