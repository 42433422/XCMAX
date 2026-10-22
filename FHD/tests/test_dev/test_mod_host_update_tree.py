from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "FHD/scripts/deploy/lib"))
import mod_tree_guard as guard  # noqa: E402


class ModTreeGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="fhd-mod-archive-guard-")
        self.root = Path(self.tmp.name)
        self.old_mods = self.root / "old-mods"
        self.source = self.root / "candidate-mods"
        self.target = self.root / "deploy" / "mods"
        self.deploy_root = self.root / "deploy"
        self.state = self.root / "apply-state"
        self.old_mods.mkdir()
        self.source.mkdir()
        self.target.mkdir(parents=True)
        self.identity = {
            "git_sha": "a" * 40,
            "version": "1.2.3",
            "release_id": "xcagi-1.2.3-" + "a" * 40,
            "admin_console_sha256": "b" * 64,
        }
        self.archive = self.deploy_root / ".deploy-last.tar.gz"
        self.deploy_root.mkdir(exist_ok=True)
        (self.deploy_root / ".build-identity.json").write_text(
            json.dumps(self.identity), encoding="utf-8"
        )
        (self.deploy_root / ".deploy-git-sha").write_text(
            self.identity["git_sha"], encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def put(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def build_previous_archive(self, mods: dict[str, dict[str, str]]) -> None:
        identity_path = self.root / ".build-identity.json"
        identity_path.write_text(json.dumps(self.identity), encoding="utf-8")
        for mod_id, files in mods.items():
            for relative, content in files.items():
                self.put(self.old_mods, f"{mod_id}/{relative}", content)
        with tarfile.open(self.archive, "w:gz") as tar:
            tar.add(identity_path, arcname="./.build-identity.json")
            tar.add(self.old_mods, arcname="./mods")
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        (self.deploy_root / ".deploy-sha256").write_text(digest, encoding="utf-8")

    def test_verified_archive_baseline_allows_bundle_update_and_preserves_local_state(self) -> None:
        self.build_previous_archive(
            {"bundled": {"manifest.json": '{"version":"1"}', "logic.py": "old"}}
        )
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.target, "bundled/data/preferences.csv", "customer preferences")
        self.put(self.target, "bundled/.secrets/local-key.txt", "synthetic secret")
        self.put(self.target, "bundled/.venv/runtime.cfg", "synthetic runtime state")
        self.put(self.source, "bundled/manifest.json", '{"version":"2"}')
        self.put(self.source, "bundled/logic.py", "new")
        self.put(self.target, ".install-receipts/account-pack/receipt.json", "signed receipt")
        self.put(self.target, ".install-receipts/account-pack/pending-deadbeef/logic.py", "pending")
        self.put(self.target, "_employees/customer-pack/private.txt", "employee data")
        self.put(self.target, "local-mod/backend.py", "customer Mod")

        guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "bundled/logic.py").read_text(), "new")
        self.assertEqual(
            (self.target / "bundled/data/preferences.csv").read_text(), "customer preferences"
        )
        self.assertEqual(
            (self.target / "bundled/.secrets/local-key.txt").read_text(), "synthetic secret"
        )
        self.assertEqual(
            (self.target / "bundled/.venv/runtime.cfg").read_text(), "synthetic runtime state"
        )
        self.assertEqual(
            (self.target / ".install-receipts/account-pack/receipt.json").read_text(),
            "signed receipt",
        )
        self.assertEqual(
            (self.target / ".install-receipts/account-pack/pending-deadbeef/logic.py").read_text(),
            "pending",
        )
        self.assertEqual(
            (self.target / "_employees/customer-pack/private.txt").read_text(), "employee data"
        )
        self.assertEqual((self.target / "local-mod/backend.py").read_text(), "customer Mod")

    def test_rollback_restores_bundle_and_keeps_new_mod_installed_after_apply(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.source, "bundled/logic.py", "candidate")
        guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.put(self.target, "new-customer-mod/backend.py", "installed after apply")
        self.put(
            self.target, ".install-receipts/new-customer-mod/receipt.json", "new signed receipt"
        )
        self.put(self.target, "bundled/data/new-upload.csv", "created after apply")
        self.put(self.target, "bundled/.secrets/new-key.txt", "synthetic secret after apply")
        self.put(self.target, "bundled/.venv/new-runtime.cfg", "synthetic runtime after apply")
        guard.rollback(self.state, self.target)

        self.assertEqual((self.target / "bundled/logic.py").read_text(), "old")
        self.assertEqual(
            (self.target / "bundled/data/new-upload.csv").read_text(), "created after apply"
        )
        self.assertEqual(
            (self.target / "bundled/.secrets/new-key.txt").read_text(),
            "synthetic secret after apply",
        )
        self.assertEqual(
            (self.target / "bundled/.venv/new-runtime.cfg").read_text(),
            "synthetic runtime after apply",
        )
        self.assertEqual(
            (self.target / "new-customer-mod/backend.py").read_text(), "installed after apply"
        )
        self.assertEqual(
            (self.target / ".install-receipts/new-customer-mod/receipt.json").read_text(),
            "new signed receipt",
        )

    def test_same_id_receipt_is_skipped_while_other_bundled_mods_update(self) -> None:
        self.build_previous_archive(
            {
                "bundled": {"logic.py": "host old"},
                "regular": {"logic.py": "regular old"},
            }
        )
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        shutil.copytree(self.old_mods / "regular", self.target / "regular")
        self.put(self.target, "bundled/logic.py", "customer installed version")
        self.put(self.source, "bundled/logic.py", "new")
        self.put(self.source, "regular/logic.py", "regular new")
        self.put(self.target, ".install-receipts/bundled/receipt.json", "signed receipt")
        self.put(
            self.target,
            ".install-receipts/bundled/pending-deadbeef/logic.py",
            "pending signed update",
        )

        guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual(
            (self.target / "bundled/logic.py").read_text(), "customer installed version"
        )
        self.assertEqual((self.target / "regular/logic.py").read_text(), "regular new")
        self.assertEqual(
            (self.target / ".install-receipts/bundled/receipt.json").read_text(), "signed receipt"
        )
        self.assertEqual(
            (self.target / ".install-receipts/bundled/pending-deadbeef/logic.py").read_text(),
            "pending signed update",
        )

    def test_missing_or_bad_digest_stamp_blocks_destructive_apply(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.source, "bundled/logic.py", "new")
        (self.deploy_root / ".deploy-sha256").write_text("0" * 64, encoding="utf-8")
        before = (self.target / "bundled/logic.py").read_text()

        with self.assertRaisesRegex(guard.GuardError, "does not match"):
            guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "bundled/logic.py").read_text(), before)
        self.assertFalse(self.state.exists())

    def test_mismatched_deployed_build_identity_blocks_apply(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.source, "bundled/logic.py", "new")
        (self.deploy_root / ".deploy-git-sha").write_text("c" * 40, encoding="utf-8")
        before = (self.target / "bundled/logic.py").read_text()

        with self.assertRaisesRegex(guard.GuardError, "Git SHA"):
            guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "bundled/logic.py").read_text(), before)
        self.assertFalse(self.state.exists())

    def test_unknown_or_modified_existing_mod_blocks_apply(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.target, "bundled/unowned.py", "local edit")
        self.put(self.source, "bundled/logic.py", "new")
        before = (self.target / "bundled/logic.py").read_text()

        with self.assertRaisesRegex(guard.GuardError, "differs from verified deployed archive"):
            guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "bundled/logic.py").read_text(), before)
        self.assertTrue((self.target / "bundled/unowned.py").is_file())
        self.assertFalse(self.state.exists())

    def test_symlinked_secret_state_blocks_before_mutation(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        outside = self.root / "outside-secret"
        outside.mkdir()
        (outside / "key.txt").write_text("outside", encoding="utf-8")
        (self.target / "bundled/.secrets").symlink_to(outside, target_is_directory=True)
        self.put(self.source, "bundled/logic.py", "new")

        with self.assertRaisesRegex(guard.GuardError, "user state is a symlink"):
            guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "bundled/logic.py").read_text(), "old")
        self.assertEqual((outside / "key.txt").read_text(), "outside")
        self.assertFalse(self.state.exists())
        # A dangling secret link is equally untrusted and must not be dropped.
        (outside / "key.txt").unlink()
        outside.rmdir()
        with self.assertRaisesRegex(guard.GuardError, "user state is a symlink"):
            guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)
        self.assertTrue((self.target / "bundled/.secrets").is_symlink())
        self.assertEqual((self.target / "bundled/logic.py").read_text(), "old")
        self.assertFalse(self.state.exists())

    def test_partial_apply_failure_rolls_back_without_deleting_receipts(self) -> None:
        self.build_previous_archive(
            {
                "bundle-a": {"logic.py": "old A"},
                "bundle-b": {"logic.py": "old B"},
            }
        )
        shutil.copytree(self.old_mods / "bundle-a", self.target / "bundle-a")
        shutil.copytree(self.old_mods / "bundle-b", self.target / "bundle-b")
        self.put(self.source, "bundle-a/logic.py", "new A")
        self.put(self.source, "bundle-b/logic.py", "new B")
        self.put(self.target, ".install-receipts/account/receipt.json", "receipt")
        self.put(self.target, ".install-receipts/account/pending-digest/payload.bin", "pending")
        original_copytree = guard.shutil.copytree

        def inject_second_candidate_failure(src, dst, *args, **kwargs):
            if Path(src).parent == self.source and Path(src).name == "bundle-b":
                raise OSError("injected second-Mod stage failure")
            return original_copytree(src, dst, *args, **kwargs)

        with patch.object(guard.shutil, "copytree", side_effect=inject_second_candidate_failure):
            with self.assertRaisesRegex(OSError, "injected"):
                guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "bundle-a/logic.py").read_text(), "old A")
        self.assertEqual((self.target / "bundle-b/logic.py").read_text(), "old B")
        self.assertEqual(
            (self.target / ".install-receipts/account/receipt.json").read_text(), "receipt"
        )
        self.assertEqual(
            (self.target / ".install-receipts/account/pending-digest/payload.bin").read_text(),
            "pending",
        )

    def test_unbundled_local_mod_is_never_pruned(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.target, "local-mod/customer.py", "keep")
        self.put(self.source, "bundled/logic.py", "new")

        guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)

        self.assertEqual((self.target / "local-mod/customer.py").read_text(), "keep")

    def test_interrupted_backup_keeps_live_mod_and_removes_incomplete_recovery(self) -> None:
        self.build_previous_archive({"bundled": {"logic.py": "old"}})
        shutil.copytree(self.old_mods / "bundled", self.target / "bundled")
        self.put(self.source, "bundled/logic.py", "new")
        original = guard.shutil.copytree

        def interrupt_backup(src, dst, *args, **kwargs):
            if Path(dst).parent == self.state / "prior":
                raise KeyboardInterrupt("injected backup interrupt")
            return original(src, dst, *args, **kwargs)

        with patch.object(guard.shutil, "copytree", side_effect=interrupt_backup):
            with self.assertRaisesRegex(KeyboardInterrupt, "backup interrupt"):
                guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)
        self.assertEqual((self.target / "bundled/logic.py").read_text(), "old")
        self.assertFalse(self.state.exists())

    def test_interrupt_after_first_swap_restores_mods_and_retains_recovery(self) -> None:
        self.build_previous_archive(
            {"bundle-a": {"logic.py": "old A"}, "bundle-b": {"logic.py": "old B"}}
        )
        for mod_id in ("bundle-a", "bundle-b"):
            shutil.copytree(self.old_mods / mod_id, self.target / mod_id)
            self.put(self.source, f"{mod_id}/logic.py", "new")
            self.put(self.target, f"{mod_id}/data/customer.txt", mod_id)
        original = guard.os.replace

        def interrupt_second_swap(src, dst):
            if Path(src).name.startswith(".fhd-stage-") and Path(dst).name == "bundle-b":
                raise KeyboardInterrupt("injected second swap interrupt")
            return original(src, dst)

        with patch.object(guard.os, "replace", side_effect=interrupt_second_swap):
            with self.assertRaisesRegex(KeyboardInterrupt, "second swap interrupt"):
                guard.apply(self.source, self.target, self.state, self.archive, self.deploy_root)
        for mod_id, content in (("bundle-a", "old A"), ("bundle-b", "old B")):
            self.assertEqual((self.target / mod_id / "logic.py").read_text(), content)
            self.assertEqual((self.target / mod_id / "data/customer.txt").read_text(), mod_id)
        self.assertTrue((self.state / "plan.json").is_file())
        self.assertFalse(any(self.target.glob(".fhd-stage-*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
