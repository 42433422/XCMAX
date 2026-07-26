# Source governance

XCMAX keeps FastAPI, Vue, Electron, and Flutter as separate delivery surfaces.
Sharing transport contracts is desirable; sharing UI source across frameworks is
not. Historical oversized files are reduced with a strangler-style ratchet rather
than a big-bang rewrite.

## CI policy

Run from the repository root:

```bash
python scripts/dev/source_governance.py
python scripts/dev/source_governance.py --top 20
```

The baseline is `config/source_governance_baseline.json`. The gate enforces:

- new production files stay below the stack soft cap;
- existing oversized files and routers never grow;
- exact-copy debt outside declared derived trees never grows;
- retired source mirrors cannot regain tracked JS, CSS, or application source;
- Git never tracks a path that its ignore rules classify as generated or local.

## Legacy static single source

`FHD/frontend/public/static` is the single editable source for the opt-in legacy
assets loaded by `FHD/frontend/index.html`. Vite copies that tree into
`templates/vue-dist/static`, which is the directory served by FastAPI.

The former `FHD/static` JS/CSS mirror is retired. The directory may contain
non-source binary assets (currently the VBCABLE driver archive), but CI rejects
new source files there.

When an oversized file is reduced, update the baseline so the improvement cannot
regress:

```bash
python scripts/dev/source_governance.py --update-baseline
```

`--force` is reserved for an explicitly reviewed policy reset.

## Decomposition order

1. Remove generated build output and local evidence from Git.
2. Generate TypeScript and Dart transport contracts from FastAPI OpenAPI.
3. Split high-churn backend routers/services by bounded context.
4. Split Vue screens into feature components and composables.
5. Split Flutter API/repository/screen files by feature.
6. Split Electron process lifecycle, backend control, IPC, updater, and tray code.

Generated contract DTOs may be replaced at build time. Authentication, retries,
caching, domain repositories, and UI behavior remain handwritten and tested.
