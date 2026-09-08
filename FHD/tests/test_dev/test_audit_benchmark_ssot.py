"""Negative examples must fail the standard gate, without importing the product."""

import copy
import json
import unittest

from scripts.dev.audit_benchmark_ssot import CATALOG, DOCUMENT, render, validate


class AuditBenchmarkStandardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_catalog_and_generated_view_agree(self):
        self.assertEqual(validate(self.catalog), [])
        self.assertEqual(DOCUMENT.read_text(encoding="utf-8"), render(self.catalog))

    def test_missing_or_duplicate_commercial_reference_is_rejected(self):
        for mode in ("missing", "duplicate"):
            with self.subTest(mode=mode):
                data = copy.deepcopy(self.catalog)
                refs = data["domains"][0]["commercial_90"]
                if mode == "missing":
                    refs.pop()
                else:
                    refs[2] = copy.deepcopy(refs[0])
                self.assertTrue(validate(data))

    def test_source_available_license_cannot_be_called_open_source(self):
        data = copy.deepcopy(self.catalog)
        data["domains"][0]["open_source_60"]["license"] = "Business-Source-License"
        self.assertTrue(validate(data))

    def test_moving_branch_cannot_replace_source_sha(self):
        data = copy.deepcopy(self.catalog)
        data["domains"][0]["open_source_60"]["source_commit"] = "main"
        self.assertTrue(validate(data))

    def test_unused_commercial_anchor_cannot_be_silently_dropped(self):
        data = copy.deepcopy(self.catalog)
        domain = data["domains"][0]
        domain["anchor_90"][2]["reference_id"] = domain["commercial_90"][0]["id"]
        self.assertTrue(validate(data))

    def test_catalog_cannot_pretend_references_were_benchmarked(self):
        data = copy.deepcopy(self.catalog)
        data["domains"][0]["commercial_90"][0]["measurement_status"] = "passed"
        self.assertTrue(validate(data))

    def test_anchor_and_weight_drift_are_rejected(self):
        for key in ("commercial_anchor_score", "open_source_pass_score"):
            data = copy.deepcopy(self.catalog)
            data[key] += 1
            self.assertTrue(validate(data))
        data = copy.deepcopy(self.catalog)
        data["axes"][0]["weight"] = 35
        self.assertTrue(validate(data))


if __name__ == "__main__":
    unittest.main()
