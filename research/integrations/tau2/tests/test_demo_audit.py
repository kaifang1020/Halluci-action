from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research.integrations.tau2.generate_demo_audit_html import (
    DEFAULT_DATA,
    generate_report,
)


class DemoAuditReportTest(unittest.TestCase):
    def test_demo_counts_and_standalone_html(self) -> None:
        report = json.loads(DEFAULT_DATA.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["unsupported"], 0)
        self.assertEqual(report["summary"]["claim_total"], 4)
        self.assertEqual(report["summary"]["undisclosed"], 0)
        self.assertEqual(report["summary"]["action_total"], 3)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.html"
            generate_report(DEFAULT_DATA, output)
            html = output.read_text(encoding="utf-8")

        self.assertIn("Halluci-Action × Tau2", html)
        self.assertIn("halluci_action_demo_audit_v1", html)
        self.assertNotIn("__REPORT_DATA__", html)


if __name__ == "__main__":
    unittest.main()
