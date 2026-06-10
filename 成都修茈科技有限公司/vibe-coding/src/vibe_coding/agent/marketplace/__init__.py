"""MODstore marketplace integration.

Lets a vibe-coding-generated :class:`CodeSkill` (or an entire
:class:`VibeWorkflowGraph`) be packaged into a MODstore-compatible
``.xcmod`` zip and published directly to the market via the admin API.

Three layers, each independently usable:

- :class:`SkillPackager` — pure Python, no network. Materialises a skill
  (or workflow) into a temp directory + a zip with the manifest layout
  documented in ``MODstore_deploy/templates/skeleton/manifest.json``.
- :class:`MODstoreClient` — thin HTTP client around the admin
  ``/api/admin/catalog`` endpoint plus the auth flow. Pure ``urllib``,
  no extra deps.
- :class:`SkillPublisher` — facade that wires both together. The natural
  entry point in scripts:

  .. code-block:: python

      pub = SkillPublisher.from_token(
          base_url="https://modstore.example.com",
          admin_token="...",
      )
      result = pub.publish_skill(skill, version="1.0.0", price=0)

The packager has zero MODstore dependency so unit tests can cover it
without spinning up the whole server. The client and publisher fail loud
when the network or auth is broken so CI gets a useful diagnostic.
"""

from __future__ import annotations

from .client import (
    MODstoreAuthError,
    MODstoreClient,
    MODstoreError,
    UploadResult,
)
from .packager import (
    PackagedArtifact,
    PackagingError,
    SkillPackager,
    SkillPackageOptions,
)
from .publisher import PublishOptions, PublishResult, SkillPublisher

__all__ = [
    "MODstoreAuthError",
    "MODstoreClient",
    "MODstoreError",
    "PackagedArtifact",
    "PackagingError",
    "PublishOptions",
    "PublishResult",
    "SkillPackager",
    "SkillPackageOptions",
    "SkillPublisher",
    "UploadResult",
]
