"""Public prices and purchase handoff must come from the commercial catalog."""
import copy
from contextlib import redirect_stderr
from io import StringIO
import json
import unittest

from build_public_site import FHD_ROOT, SITE_ROOT, build_pricing


class PublicPricingTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((FHD_ROOT / "config/saas_plans.json").read_text())

    def test_public_catalog_does_not_publish_legacy_or_test_prices(self):
        config = copy.deepcopy(self.config)
        config["plans"] += config.get("legacy_plans", [])
        config["plans"].append({"id": "test-only", "amount_cents": 1})
        pricing = build_pricing(config)
        self.assertEqual({p["id"] for p in pricing["all_plans"]}, {"saas-personal-free", "saas-trial-30", "saas-permanent-standard"})
        self.assertEqual([p["id"] for p in pricing["homepage_plans"]], ["saas-permanent-standard"])
        self.assertEqual(pricing["commercial_terms"]["customization_from_cents"], config["commercial_terms"]["customization_from_cents"])

    def test_launch_campaign_is_disabled_until_fulfilment_is_verified(self):
        pricing = build_pricing(self.config)
        self.assertEqual(
            pricing["commercial_terms"]["launch_campaign"],
            {"enabled": False, "starts_at": None, "ends_at": None, "benefits": []},
        )
        self.assertEqual(pricing["homepage_plans"][0]["amount_cents"], 300000)
        self.assertEqual(pricing["commercial_terms"]["customization_from_cents"], 99900)

    def test_published_prices_and_purchase_links_match_the_source(self):
        published = json.loads((SITE_ROOT / "site/data/public-site.json").read_text())
        self.assertEqual(published["pricing"], build_pricing(self.config))
        for name in ("index.html", "pricing.html"):
            html = (SITE_ROOT / name).read_text()
            self.assertIn("/market/account-plans?plan=saas-permanent-standard", html)
            self.assertIn('data-ssot="customization-from"', html)
            self.assertIn("/market/recharge", html)
            self.assertIn("/contact.html#quick-inquiry", html)
            self.assertTrue("不含企业业务" in html, name)
            for plan in self.config.get("legacy_plans", []):
                self.assertNotIn(plan["id"], html)

    def test_missing_customization_price_fails_without_inventing_a_price(self):
        del self.config["commercial_terms"]["customization_from_cents"]
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            build_pricing(self.config)


if __name__ == "__main__":
    unittest.main()
