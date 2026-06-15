"""High-level publisher that ties packaging + upload together.

Most callers don't want to think about staging directories or boundary
strings — they want to hand a :class:`CodeSkill` to a function and get
back a "yes it's live, here's the catalog id" confirmation. That's
:meth:`SkillPublisher.publish_skill`.

Three failure modes are surfaced loudly so CI / scripts can react:

- :class:`PackagingError` (from :mod:`packager`) when the skill cannot be
  bundled (invalid pkg_id / unwritable output dir / …).
- :class:`MODstoreAuthError` when the token is missing or the server
  rejects it.
- :class:`MODstoreError` for any other HTTP-side issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..._internals import CodeSkill
from .client import (
    MODstoreClient,
    MODstoreError,
    UploadResult,
)
from .packager import (
    PackagedArtifact,
    PackagingError,
    SkillPackageOptions,
    SkillPackager,
)


@dataclass(slots=True)
class PublishOptions:
    """Bundle of packaging + market metadata for one publish call."""

    pkg_id: str = ""
    version: str = ""
    name: str = ""
    description: str = ""
    price: float = 0.0
    artifact: str = "mod"
    industry: str = "通用"
    author: str = "vibe-coding"
    output_dir: str | Path | None = None
    extra_manifest: dict[str, Any] = field(default_factory=dict)

    def to_packager_options(self) -> SkillPackageOptions:
        return SkillPackageOptions(
            pkg_id=self.pkg_id,
            version=self.version,
            name=self.name,
            description=self.description,
            author=self.author,
            industry=self.industry,
            artifact=self.artifact,
            extra_manifest=dict(self.extra_manifest),
        )


@dataclass(slots=True)
class PublishResult:
    """Outcome of :meth:`SkillPublisher.publish_skill`."""

    skill_id: str
    artifact: PackagedArtifact
    upload: UploadResult | None = None
    dry_run: bool = False
    error: str = ""

    @property
    def published(self) -> bool:
        return self.upload is not None and not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "artifact": self.artifact.to_dict(),
            "upload": self.upload.to_dict() if self.upload else None,
            "dry_run": self.dry_run,
            "error": self.error,
            "published": self.published,
        }


class SkillPublisher:
    """Package + upload a :class:`CodeSkill` to MODstore in one call."""

    def __init__(
        self,
        client: MODstoreClient,
        *,
        packager: SkillPackager | None = None,
    ) -> None:
        self.client = client
        self.packager = packager or SkillPackager()

    @classmethod
    def from_token(
        cls,
        *,
        base_url: str,
        admin_token: str,
        verify_ssl: bool = True,
    ) -> SkillPublisher:
        return cls(
            client=MODstoreClient.from_token(
                base_url=base_url,
                access_token=admin_token,
                verify_ssl=verify_ssl,
            )
        )

    @classmethod
    def from_credentials(
        cls,
        *,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
    ) -> SkillPublisher:
        client = MODstoreClient(base_url=base_url, verify_ssl=verify_ssl)
        client.login(username, password)
        return cls(client=client)

    # ------------------------------------------------------------------ API

    def publish_skill(
        self,
        skill: CodeSkill,
        *,
        options: PublishOptions | None = None,
        siblings: Iterable[CodeSkill] | None = None,
        dry_run: bool = False,
    ) -> PublishResult:
        """Package ``skill`` then upload it (unless ``dry_run=True``)."""
        opts = options or PublishOptions()
        if opts.output_dir is not None:
            self.packager = SkillPackager(output_dir=opts.output_dir)
        artifact = self.packager.package_skill(
            skill,
            options=opts.to_packager_options(),
            siblings=siblings,
        )
        result = PublishResult(skill_id=skill.skill_id, artifact=artifact, dry_run=dry_run)
        if dry_run:
            return result
        try:
            upload = self.client.upload_catalog(
                artifact.archive_path,
                pkg_id=artifact.pkg_id,
                version=artifact.version,
                name=artifact.name,
                description=opts.description or artifact.manifest.get("description", ""),
                price=opts.price,
                artifact=artifact.artifact,
                industry=opts.industry,
            )
        except MODstoreError as exc:
            result.error = str(exc)
            return result
        result.upload = upload
        return result

    def publish_workflow(
        self,
        skills: list[CodeSkill],
        *,
        options: PublishOptions,
        dry_run: bool = False,
    ) -> PublishResult:
        """Bundle multiple skills into one mod and publish it.

        First skill is the "primary" skill; the rest ride along as
        ``siblings`` inside the same ``.xcmod``. The publish options'
        ``pkg_id`` is required (otherwise the package would default to
        ``vc-<first.skill_id>`` which is rarely what the user wants for
        a workflow bundle).
        """
        if not skills:
            raise PackagingError("publish_workflow needs at least one skill")
        if not options.pkg_id:
            raise PackagingError(
                "PublishOptions.pkg_id is required when bundling a workflow"
            )
        head, tail = skills[0], skills[1:]
        return self.publish_skill(
            head, options=options, siblings=tail, dry_run=dry_run
        )


__all__ = [
    "PublishOptions",
    "PublishResult",
    "SkillPublisher",
]
