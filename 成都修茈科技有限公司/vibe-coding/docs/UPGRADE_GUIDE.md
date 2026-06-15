# Upgrade Guide

How to evolve this standalone package safely.

## Day-to-day

1. Make changes only inside `src/vibe_coding/` plus `tests/` / `examples/`.
2. Run `pytest tests/` until green.
3. Bump `src/vibe_coding/_version.py` (`__version__ = "x.y.z"`).
4. Add a one-line entry to `CHANGELOG.md`.
5. Commit. The whole folder is self-contained — moving / branching it is a
   simple `cp -r` (or `git subtree split`).

## When upstream `eskill-prototype` evolves

The upstream tree is the authoritative source for these modules:

- `runtime/` (every file in `_legacy_models.py`, `validator.py`, `sandbox.py`,
  `diagnostics.py`, `patch_generator.py`, `runtime.py`, `store.py`,
  `hybrid.py`, plus `runtime/__init__.py`)
- `nl/llm.py`, `nl/prompts.py`, `nl/__init__.py`
- `code_factory.py`, `workflow_models.py`, `workflow_factory.py`

Pull updates with the sync script:

```bash
python scripts/sync_from_eskill.py             # write
python scripts/sync_from_eskill.py --check     # diff only
python scripts/sync_from_eskill.py --source ../some-other-eskill-fork
```

The script applies the import-rewrite rules in `REWRITERS` so the standalone
package stays self-contained. Re-run tests after syncing.

## Hand-maintained files (do NOT add to the sync script)

- `__init__.py`
- `_internals/*` (lifted once at v0.1.0; only update if upstream `models.py`
  changes the dataclass shape)
- `audit.py`
- `cli.py`, `__main__.py`
- `facade.py`
- `workflow_engine.py`

These intentionally drop the config-layer (`ESkill` / `ESkillRuntime` /
`JsonSkillStore` / `ESkillNodeWrapper`) hooks that exist upstream. If upstream
adds a *new* code-layer concept that should propagate, edit these files
manually and bump the version.

## Investigating new ideas without breaking production

Branch the folder:

```bash
cp -r vibe-coding vibe-coding-experimental
cd vibe-coding-experimental
# edit / experiment / break things
```

The original `vibe-coding/` keeps working in any project that depends on it.
When the experiment is mature, fold the changes back via either a manual
diff or by porting them upstream and re-running `sync_from_eskill.py`.

## Releasing as a wheel

```bash
pip install build
python -m build
twine upload dist/*
```

`pyproject.toml` already has the metadata — only the URL fields under
`[project.urls]` may need editing depending on where you publish.
