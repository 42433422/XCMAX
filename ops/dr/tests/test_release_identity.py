"""The DR boundary accepts only the immutable release's original identity."""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "release_identity", Path(__file__).parents[1] / "xcmax_release_order.py"
)
assert SPEC and SPEC.loader
ORDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORDER)


class ReleaseIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sha = "a" * 40
        self.original = b"the exact uncompressed immutable Git artifact"

    def fixture(self, component: str) -> tuple[Path, dict[str, str]]:
        digest = hashlib.sha256(self.original).hexdigest()
        identity = {
            "git_sha": self.sha,
            "product_version": "1.2.3",
            "artifact_sha256": digest,
            "release_id": f"xcagi-1.2.3-{self.sha}",
        }
        if component == "modstore":
            manifest = self.root / "modstore-release.json"
            payload = identity
            (self.root / "modstore-source.tar.gz").write_bytes(
                gzip.compress(self.original)
            )
            (self.root / "modstore-static.tar.gz").write_bytes(
                gzip.compress(b"static build")
            )
        else:
            manifest = self.root / "fhd-manifest.json"
            payload = {
                "git_sha": self.sha,
                "version": "1.2.3",
                "sha256": digest,
                "release_id": identity["release_id"],
                "artifact": "fhd-runtime.tar.gz",
                "deploy_mode": "tarball",
            }
            (self.root / "fhd-runtime.tar.gz").write_bytes(self.original)
        manifest.write_text(json.dumps(payload))
        self.write_transit_manifest(component)
        return manifest, identity

    def write_transit_manifest(self, component: str) -> None:
        members = sorted(
            p for p in self.root.iterdir() if not p.name.endswith("MANIFEST.txt")
        )
        (self.root / f"{component}.MANIFEST.txt").write_text(
            "".join(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                for path in members
            )
        )

    def test_transport_compression_preserves_original_modstore_artifact_digest(
        self,
    ) -> None:
        self.fixture("modstore")
        self.assertEqual(
            ORDER.verify_input(self.root, self.sha, "modstore"),
            "modstore-source.tar.gz",
        )
        # Even a regenerated transport checksum cannot legitimize a partial or
        # altered source archive with the same advertised commit.
        (self.root / "modstore-source.tar.gz").write_bytes(
            gzip.compress(b"partial source")
        )
        self.write_transit_manifest("modstore")
        with self.assertRaisesRegex(ValueError, "original manifest"):
            ORDER.verify_input(self.root, self.sha, "modstore")

    def test_fhd_transit_checksum_cannot_replace_original_artifact_digest(self) -> None:
        self.fixture("fhd")
        self.assertEqual(
            ORDER.verify_input(self.root, self.sha, "fhd"), "fhd-runtime.tar.gz"
        )
        (self.root / "fhd-runtime.tar.gz").write_bytes(b"different archive")
        self.write_transit_manifest("fhd")
        with self.assertRaisesRegex(ValueError, "original manifest"):
            ORDER.verify_input(self.root, self.sha, "fhd")

    def test_missing_duplicate_and_path_escape_manifest_members_are_rejected(
        self,
    ) -> None:
        self.fixture("modstore")
        path = self.root / "modstore.MANIFEST.txt"
        original = path.read_text()
        for text in (
            original.splitlines()[0],
            original + original,
            original + "a" * 64 + "  ../outside\n",
        ):
            with self.subTest(text=text):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    ORDER.verify_input(self.root, self.sha, "modstore")

    def test_symlink_manifest_is_rejected(self) -> None:
        manifest, _identity = self.fixture("modstore")
        outside = self.root / "outside.json"
        manifest.rename(outside)
        manifest.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "regular file"):
            ORDER.verify_input(self.root, self.sha, "modstore")

    def test_modstore_uses_existing_public_contract_and_version_in_release_id(
        self,
    ) -> None:
        manifest, identity = self.fixture("modstore")
        payload = {"ok": True, **identity}
        payload.pop("product_version")
        ORDER.verify_health(manifest, self.sha, "modstore", payload)
        for field, wrong in (
            ("ok", False),
            ("git_sha", "b" * 40),
            ("artifact_sha256", "b" * 64),
            ("release_id", f"xcagi-1.2.4-{self.sha}"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    ORDER.verify_health(
                        manifest, self.sha, "modstore", {**payload, field: wrong}
                    )

    def test_fhd_build_and_public_identity_must_agree_and_be_ready(self) -> None:
        manifest, identity = self.fixture("fhd")
        payload = {
            "status": "healthy",
            "degradedReasons": [],
            "build": identity,
            "git_sha": self.sha,
            "release_id": identity["release_id"],
        }
        ORDER.verify_health(manifest, self.sha, "fhd", payload)
        for field, wrong in (
            ("status", "degraded"),
            ("degradedReasons", ["database"]),
            ("git_sha", "b" * 40),
            ("release_id", "stale"),
            ("build", {}),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    ORDER.verify_health(
                        manifest, self.sha, "fhd", {**payload, field: wrong}
                    )
        altered = copy.deepcopy(payload)
        altered["build"]["artifact_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            ORDER.verify_health(manifest, self.sha, "fhd", altered)


if __name__ == "__main__":
    unittest.main()
