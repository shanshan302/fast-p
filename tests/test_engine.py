import unittest

from fast_p.engine import FastCliError, brand_matches, find_match, model_matches
from fast_p.models import InputRow


def payload(platform, items):
    return {
        "result": {
            "platforms": [{
                "platformId": platform,
                "platformName": platform,
                "success": True,
                "noData": False,
                "data": items,
            }]
        }
    }


def candidate(brand="ACME", price=2.0):
    return {
        "part_number": "ABC123-A",
        "manufacturer": brand,
        "product_url": "https://example.test/ABC123",
        "price_tiers": [{"quantity": 100, "unit_price": price}],
    }


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.row = InputRow(2, "SKU-1", "ABC123", "ACME", 1.0, 100)

    def test_first_match_stops_later_platforms(self):
        calls = []

        def collect(model, platform):
            calls.append(platform)
            return payload(platform, [candidate()])

        result = find_match(self.row, ["hqchip", "ichunt"], collect)
        self.assertEqual("OK", result.status)
        self.assertEqual("hqchip", result.platform)
        self.assertEqual(["hqchip"], calls)

    def test_failure_falls_back_to_next_platform(self):
        calls = []

        def collect(model, platform):
            calls.append(platform)
            if platform == "hqchip":
                raise FastCliError("temporary failure")
            return payload(platform, [candidate()])

        result = find_match(self.row, ["hqchip", "ichunt"], collect)
        self.assertEqual("OK", result.status)
        self.assertEqual("ichunt", result.platform)
        self.assertEqual(["hqchip", "ichunt"], calls)

    def test_business_filters(self):
        self.assertTrue(model_matches("ABC123", "ABC123-A"))
        self.assertTrue(brand_matches("ACME Semiconductor", "ACME"))
        result = find_match(
            self.row,
            ["hqchip"],
            lambda model, platform: payload(platform, [candidate(price=0.8)]),
        )
        self.assertEqual("BRAND_NO_OK", result.status)

    def test_platform_runtime_errors_are_not_reported_as_no_model(self):
        result = find_match(
            self.row,
            ["hqchip"],
            lambda model, platform: {
                "result": {"platforms": [{
                    "platformId": platform,
                    "success": False,
                    "noData": False,
                    "error": "page crashed",
                    "data": [],
                }]},
            },
        )
        self.assertEqual("ERROR", result.status)
        self.assertIn("page crashed", result.reason)


if __name__ == "__main__":
    unittest.main()
