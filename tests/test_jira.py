import contextlib
import io
import os
import unittest
from unittest.mock import patch

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import jira
import jira_client


class JiraCommandTests(unittest.TestCase):

    @patch.dict(os.environ, {"JIRA_BASE_URL": "https://jira.example.com/jira"}, clear=True)
    @patch("jira.webbrowser.open", return_value=True)
    def test_opens_ticket_without_api_token(self, open_browser):
        self.assertEqual(jira.main(["proj-123"]), 0)
        open_browser.assert_called_once_with("https://jira.example.com/jira/browse/PROJ-123")

    @patch.dict(os.environ, {"JIRA_BASE_URL": "https://jira.example.com"}, clear=True)
    @patch("jira.webbrowser.open", return_value=False)
    def test_reports_browser_failure(self, open_browser):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(jira.main(["PROJ-123"]), 1)
        self.assertIn("Could not open", stderr.getvalue())

    def test_rejects_invalid_ticket_key(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {"JIRA_BASE_URL": "https://jira.example.com"}, clear=True):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(jira.main(["https://example.com"]), 1)
        self.assertIn("valid Jira ticket key", stderr.getvalue())

    def test_rejects_missing_base_url(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(jira_client.JiraError):
                jira_client.jira_base_url()


if __name__ == "__main__":
    unittest.main()
