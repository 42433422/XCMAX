#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "xcmax_dr_failover_guard.py"
SPEC = importlib.util.spec_from_file_location("xcmax_dr_failover_guard", MODULE_PATH)
assert SPEC and SPEC.loader
GUARD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GUARD
SPEC.loader.exec_module(GUARD)


class FailoverDecisionTest(unittest.TestCase):
    def base(self, **overrides: object) -> object:
        values: dict[str, object] = {
            "enabled": True,
            "primary_https_ok": False,
            "primary_ssh_ok": False,
            "authoritative_addresses": {"43.138.211.142"},
            "secondary_ip": "43.138.211.142",
            "standby_ready": True,
            "fence_ready": True,
            "previous_consecutive": 2,
            "threshold": 3,
        }
        values.update(overrides)
        return GUARD.decide(**values)

    def test_promotes_only_after_all_guards(self) -> None:
        decision = self.base()
        self.assertTrue(decision.promote)
        self.assertEqual(decision.consecutive, 3)

    def test_primary_health_or_reachability_resets_counter(self) -> None:
        self.assertEqual(
            self.base(primary_https_ok=True).reason, "primary_https_healthy"
        )
        self.assertEqual(
            self.base(primary_ssh_ok=True).reason, "primary_host_reachable"
        )
        self.assertEqual(self.base(primary_ssh_ok=True).consecutive, 0)

    def test_dns_must_exclusively_select_dr(self) -> None:
        decision = self.base(
            authoritative_addresses={"119.27.178.147", "43.138.211.142"}
        )
        self.assertFalse(decision.promote)
        self.assertEqual(decision.reason, "authoritative_dns_has_not_fenced_primary")

    def test_fence_proof_remains_mandatory(self) -> None:
        decision = self.base(fence_ready=False)
        self.assertFalse(decision.promote)
        self.assertEqual(decision.reason, "provider_fence_proof_missing")

    def test_fence_proof_requires_root_private_fresh_file(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "proof.json"
            path.write_text(
                '{"primary_ip":"119.27.178.147","fenced":true,"expires_at":200}',
                encoding="utf-8",
            )
            os.chmod(path, 0o600)
            expected = os.geteuid() == 0
            self.assertEqual(
                GUARD.valid_fence_proof(path, "119.27.178.147", 100),
                expected,
            )
            self.assertFalse(GUARD.valid_fence_proof(path, "119.27.178.147", 201))

    def test_fence_command_must_be_root_owned_and_not_group_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = (Path(tempdir) / "fence").resolve()
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(path, 0o755)
            self.assertEqual(GUARD.trusted_executable(path), os.geteuid() == 0)
            os.chmod(path, 0o775)
            self.assertFalse(GUARD.trusted_executable(path))


if __name__ == "__main__":
    unittest.main()
