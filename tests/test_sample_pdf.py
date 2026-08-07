import os
import unittest
from pathlib import Path

from app.parsers import parse_pdf


@unittest.skipUnless(os.getenv("RUN_SLOW_TESTS") == "1", "Set RUN_SLOW_TESTS=1 for the 131-page PDF smoke test")
class SamplePdfSmokeTest(unittest.TestCase):
    def test_lukoil_report(self):
        path = Path(__file__).resolve().parents[1] / "samples" / "lukoil_annual_report_2025.pdf"
        result = parse_pdf(path, lambda *_: None)
        self.assertEqual(result["metadata"]["document_type"], "annual_report")
        self.assertEqual(result["metadata"]["reporting_year"], 2025)
        self.assertGreater(result["metadata"]["page_count"], 100)
        self.assertGreater(len(result["tables"]), 50)
        self.assertGreater(len(result["operational_metrics"]), 50)


if __name__ == "__main__":
    unittest.main()
