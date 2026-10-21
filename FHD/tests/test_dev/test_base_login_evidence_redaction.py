"""Static evidence integrity checks; these do not repeat Windows acceptance."""

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "FHD/docs/evidence/e2e/feature-acceptance-20260922/base-login"


class EvidenceRedactionTests(unittest.TestCase):
    def test_both_session_identifier_copies_are_redacted(self):
        record = json.loads((EVIDENCE / "base-login-windows-run.json").read_text())
        case = next(case for case in record["cases"] if case["id"] == "W3")
        result = case["facts"]["validate_after_restart"]
        self.assertEqual(result["data"]["session_id"], "[REDACTED_SESSION_ID]")
        observed = json.loads(case["observed"])
        self.assertEqual(
            observed["validate_after_restart"]["data"]["session_id"], "[REDACTED_SESSION_ID]"
        )
        self.assertTrue(result["valid"])
        self.assertEqual(len(record["cases"]), 9)
        self.assertTrue(all(case["verdict"] == "PASS" for case in record["cases"]))

    def test_catalog_references_redacted_record_digest(self):
        digest = hashlib.sha256((EVIDENCE / "base-login-windows-run.json").read_bytes()).hexdigest()
        catalog = (ROOT / "成都修茈科技有限公司/data/capabilities/catalog.json").read_text()
        self.assertEqual(catalog.count(digest), 1)

    def test_collector_does_not_persist_full_validation_response(self):
        source = (EVIDENCE / "windows/accept-base-login.ps1").read_text()
        self.assertNotIn("validate_after_restart = $sv2.body", source)
        self.assertIn("validate_after_restart = [ordered]@{", source)
        self.assertIn("success = ((Get-BodyField $sv2.body 'success') -eq $true)", source)
        self.assertIn("valid = ($sv2Valid -eq $true)", source)


if __name__ == "__main__":
    unittest.main()
