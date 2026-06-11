# MODstore Marketplace Integration

vibe-coding can package any `CodeSkill` (or a workflow's worth of skills)
into a MODstore-compatible `.xcmod` zip and publish it directly to the
admin catalog API.

## Quick start

```python
from vibe_coding import VibeCoder, OpenAILLM

coder = VibeCoder(llm=OpenAILLM(api_key="..."), store_dir="./data")
skill = coder.code("Reverse a string")

# Publish straight to a MODstore deployment (admin token required)
result = coder.publish_skill(
    skill.skill_id,
    base_url="https://modstore.example.com",
    admin_token="...",
    version="1.0.0",
    name="Reverse String",
    description="Reverses any input string.",
    price=0.0,
    artifact="mod",     # or "employee_pack"
)
print(result.published, result.upload.item_id)
```

A `dry_run=True` invocation still produces the `.xcmod` file on disk
without contacting the network — handy for inspecting the manifest or
feeding it to `modman` locally.

## CLI

```bash
# Set up auth once
export MODSTORE_BASE_URL=https://modstore.example.com
export MODSTORE_ADMIN_TOKEN=...

# Publish
python -m vibe_coding publish reverse-string --version 1.0.0 --price 0
```

Flags:

- `--base-url` / `--admin-token` — override the env vars.
- `--name` / `--description` / `--price` — catalog metadata.
- `--artifact` — `mod` (default) or `employee_pack`.
- `--industry` — passed straight to MODstore (`通用` by default).
- `--no-verify-ssl` — for self-signed deployments.
- `--dry-run` — produce the zip; skip the upload.

## What's inside the .xcmod?

The packager produces the layout that `modstore_server` expects:

```
<pkg_id>-<version>.xcmod
├── manifest.json
├── README.md
├── backend/
│   ├── __init__.py
│   ├── mod_init.py        # blueprint init: registers FastAPI router
│   ├── blueprints.py      # POST /<pkg_id>/run for the skill
│   └── skill.py           # verbatim skill source code
├── frontend/
│   └── routes.json        # placeholder (manifest validator requires it)
└── meta/
    ├── skill.json         # full CodeSkill dump (every version)
    ├── siblings.json      # for workflow bundles
    └── tests.json         # built-in test cases for verifiers
```

The manifest matches the schema in
`MODstore_deploy/templates/skeleton/manifest.json` and includes a
`vibe_coding` block recording the source skill_id / active_version so
downstream consumers can trace each mod back to its generator.

## Publishing a workflow

When `coder.workflow()` produces a graph with multiple skills, bundle
them into one `.xcmod`:

```python
from vibe_coding import (
    VibeCoder,
    SkillPublisher,
    PublishOptions,
)

skills = [coder.code_store.get_code_skill(sid) for sid in workflow.code_skill_ids]
pub = SkillPublisher.from_token(
    base_url="https://modstore.example.com",
    admin_token="...",
)
result = pub.publish_workflow(
    skills,
    options=PublishOptions(
        pkg_id="weather-stack",
        version="1.0.0",
        name="Weather Stack",
        description="Geo lookup + dressing recommendation.",
    ),
)
```

The first skill becomes the "primary" exported skill; the rest ride
along as siblings (each gets its own `backend/skill_<id>.py` and an
entry in `manifest.comms.exports`).

## Layered API

If you need fine-grained control, the marketplace package ships three
layers — pick the one that matches your use case:

```python
from vibe_coding.agent.marketplace import (
    SkillPackager, MODstoreClient, SkillPublisher,
    PackagedArtifact, PublishOptions,
)
```

- `SkillPackager` — pure offline; produces a `.xcmod` zip.
- `MODstoreClient` — HTTP client for the admin API (login, upload, list).
- `SkillPublisher` — convenience facade that wires both together.
