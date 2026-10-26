import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import jira_backlog
import jira_client


class SearchTests(unittest.TestCase):
    @patch("jira_client.build_opener")
    def test_paginates_and_encodes_jql(self, opener):
        responses = [
            {"total": 3, "issues": [{"key": f"P-{i}", "fields": {}} for i in (1, 2)]},
            {"total": 3, "issues": [{"key": "P-3", "fields": {}}]},
        ]
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.side_effect = [json.dumps(x).encode() for x in responses]
        result = jira_client.search_issues("project = P AND status != Done",
                                          "https://jira.example.com", "token",
                                          max_results=3, page_size=2)
        self.assertEqual([issue["key"] for issue in result], ["P-1", "P-2", "P-3"])
        calls = opener.return_value.open.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("startAt=0", calls[0].args[0].full_url)
        self.assertIn("startAt=2", calls[1].args[0].full_url)
        self.assertIn("jql=project+%3D+P", calls[0].args[0].full_url)
        self.assertEqual(calls[0].args[0].get_header("Authorization"), "Bearer token")
        self.assertIsInstance(opener.call_args.args[0], jira_client.NoRedirects)

    @patch("jira_client.build_opener")
    def test_limit_stops_pagination(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({
            "total": 100, "issues": [{"key": "P-1", "fields": {}}]
        }).encode()
        result = jira_client.search_issues("project=P", "https://jira.example.com",
                                          "token", max_results=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_rejects_bad_arguments(self):
        for jql, limit, size in [("", 10, 5), ("x", 0, 5), ("x", 1001, 5),
                                 ("x", 10, 0), ("x", 10, 101)]:
            with self.subTest(jql=jql, limit=limit, size=size):
                with self.assertRaises(jira_client.JiraError):
                    jira_client.search_issues(jql, "https://jira.example.com",
                                              "token", max_results=limit, page_size=size)

    @patch("jira_client.build_opener")
    def test_rejects_malformed_response(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        for body in [b"bad json", b"[]", b'{"total":1,"issues":{}}',
                     b'{"total":1,"issues":[{"key":"P-1"}]}']:
            with self.subTest(body=body):
                response.read.return_value = body
                with self.assertRaises(jira_client.JiraError):
                    jira_client.search_issues("project=P", "https://jira.example.com", "token")

    @patch("jira_backlog.search_issues")
    @patch("jira_backlog.configuration", return_value=("https://jira.example.com", "token"))
    def test_cli_json(self, config, search):
        search.return_value = [{"key": "P-1", "fields": {"summary": "Something"}}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(jira_backlog.main(["--jql", "project = P", "--limit", "5"]), 0)
        data = json.loads(output.getvalue())
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["issues"][0]["key"], "P-1")
        search.assert_called_once_with("project = P", "https://jira.example.com",
                                       "token", max_results=5, page_size=50)

    @patch("jira_backlog.search_issues", return_value=[{"key": "P-1", "fields": {"summary": "secret-test-token"}}])
    @patch("jira_backlog.configuration", return_value=("https://jira.example.com", "secret-test-token"))
    def test_no_secret_in_output(self, config, search):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(jira_backlog.main(["--jql", "project=P"]), 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("secret-test-token", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
