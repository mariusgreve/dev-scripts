import contextlib
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import jira_branch


ENV = {"JIRA_BASE_URL": "https://jira.example.com/jira/", "JIRA_TOKEN": "secret-test-token"}


class ConfigurationTests(unittest.TestCase):
    def test_configuration(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(
                jira_branch.configuration(),
                ("https://jira.example.com/jira", "secret-test-token"),
            )

    def test_invalid_configuration(self):
        cases = [
            {},
            {"JIRA_BASE_URL": ENV["JIRA_BASE_URL"]},
            {**ENV, "JIRA_BASE_URL": "http://jira.example.com"},
            {**ENV, "JIRA_BASE_URL": "https://user:pass@jira.example.com"},
            {**ENV, "JIRA_BASE_URL": "https://jira.example.com?query=x"},
            {**ENV, "JIRA_BASE_URL": "https://jira.example.com#fragment"},
            {**ENV, "JIRA_BASE_URL": "https://jira.example.com:0"},
            {**ENV, "JIRA_BASE_URL": "https://jira.example.com:invalid"},
            {**ENV, "JIRA_BASE_URL": "https://jira.example.com\\evil"},
            {**ENV, "JIRA_TOKEN": "token with spaces"},
            {**ENV, "JIRA_TOKEN": "token\n"},
        ]
        for env in cases:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                with self.assertRaises(jira_branch.BranchError):
                    jira_branch.configuration()

    def test_loopback_configuration(self):
        for host in ("localhost", "127.0.0.1", "[::1]"):
            with self.subTest(host=host), patch.dict(
                os.environ, {**ENV, "JIRA_BASE_URL": f"http://{host}:8080"}
            ):
                self.assertEqual(jira_branch.configuration()[0], f"http://{host}:8080")


class BranchNameTests(unittest.TestCase):
    def test_names(self):
        for title, prefix, expected in [
            ("Fix login: retry!", "", "PROJ-123/fix-login-retry"),
            ("Fix login", "feature", "feature/PROJ-123/fix-login"),
            ("Fix login", "users/alice", "users/alice/PROJ-123/fix-login"),
            ("  Cafe\u0301 & d\u00e9j\u00e0 vu -- 42  ", "", "PROJ-123/cafe-deja-vu-42"),
            ("$(touch /tmp/unwanted); fix", "", "PROJ-123/touch-tmp-unwanted-fix"),
        ]:
            with self.subTest(title=title, prefix=prefix):
                self.assertEqual(jira_branch.branch_name("PROJ-123", title, prefix), expected)

    def test_empty_slug(self):
        for title in ("!!!", "\u65e5\u672c\u8a9e", " "):
            with self.subTest(title=title), self.assertRaises(jira_branch.BranchError):
                jira_branch.branch_name("PROJ-123", title, "")


class UsernameTests(unittest.TestCase):
    @patch("jira_branch.subprocess.run")
    def test_username_removes_non_alphanumeric_characters(self, run):
        run.return_value = MagicMock(returncode=0, stdout="marius.greve\n")
        self.assertEqual(jira_branch.current_username(), "mariusgreve")
        run.assert_called_once_with(["whoami"], capture_output=True, text=True, check=False)

    @patch("jira_branch.subprocess.run")
    def test_username_requires_alphanumeric_characters(self, run):
        run.return_value = MagicMock(returncode=0, stdout="... \n")
        with self.assertRaisesRegex(jira_branch.BranchError, "at least one letter or digit"):
            jira_branch.current_username()


class FetchTests(unittest.TestCase):
    @patch("jira_branch.build_opener")
    def test_request_contract(self, build_opener):
        response = build_opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps(
            {"key": "PROJ-123", "fields": {"summary": "Fix login"}}
        ).encode()
        self.assertEqual(
            jira_branch.fetch_title("PROJ-123", "https://jira.example.com/jira", ENV["JIRA_TOKEN"]),
            "Fix login",
        )
        request = build_opener.return_value.open.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://jira.example.com/jira/rest/api/2/issue/PROJ-123?fields=summary",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + ENV["JIRA_TOKEN"])
        self.assertEqual(build_opener.return_value.open.call_args.kwargs, {"timeout": 30})
        self.assertIsInstance(build_opener.call_args.args[0], jira_branch.NoRedirects)

    @patch("jira_branch.build_opener")
    def test_bad_responses(self, build_opener):
        response = build_opener.return_value.open.return_value.__enter__.return_value
        for data in (
            b"not json", b"\xff", b"[]",
            b'{"key":"OTHER-1","fields":{"summary":"Title"}}',
            b'{"key":"PROJ-123"}',
            b'{"key":"PROJ-123","fields":{"summary":null}}',
            b'{"key":"PROJ-123","fields":{"summary":" "}}',
            b'{"key":"PROJ-123","fields":{"summary":123}}',
            b'{"key":"PROJ-123","fields":{"summary":"secret-test-token"}}',
        ):
            with self.subTest(data=data), self.assertRaises(jira_branch.BranchError):
                response.read.return_value = data
                jira_branch.fetch_title("PROJ-123", "https://jira.example.com", ENV["JIRA_TOKEN"])

    @patch("jira_branch.build_opener")
    def test_connection_errors(self, build_opener):
        for error, message in [
            (URLError(TimeoutError()), "timed out"),
            (URLError(ssl.SSLError()), "certificate"),
            (URLError("unreachable"), "Could not connect"),
            (HTTPException(), "Could not connect"),
            (OSError(), "Could not connect"),
        ]:
            with self.subTest(error=error), self.assertRaisesRegex(jira_branch.BranchError, message):
                build_opener.return_value.open.side_effect = error
                jira_branch.fetch_title("PROJ-123", "https://jira.example.com", ENV["JIRA_TOKEN"])

    @patch("jira_branch.build_opener")
    def test_http_errors(self, build_opener):
        for code in (301, 302, 401, 403, 404, 500):
            with self.subTest(code=code):
                body = io.BytesIO(b"sensitive server response")
                build_opener.return_value.open.side_effect = HTTPError(
                    "https://jira.example.com", code, "error", {}, body
                )
                with self.assertRaises(jira_branch.BranchError) as caught:
                    jira_branch.fetch_title("PROJ-123", "https://jira.example.com", ENV["JIRA_TOKEN"])
                self.assertNotIn("sensitive", str(caught.exception))
                self.assertTrue(body.closed)

    def test_redirect_is_not_followed(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()

            def log_message(self, *args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            try:
                with self.assertRaisesRegex(jira_branch.BranchError, "redirect"):
                    jira_branch.fetch_title(
                        "PROJ-123", f"http://127.0.0.1:{server.server_port}", ENV["JIRA_TOKEN"]
                    )
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(requests, ["/rest/api/2/issue/PROJ-123?fields=summary"])


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.run_git("init", "--quiet")
        self.run_git("-c", "user.name=Test", "-c", "user.email=test@example.com",
                     "-c", "commit.gpgsign=false", "commit", "--quiet", "--allow-empty", "-m", "Initial")
        self.original_branch = self.run_git("branch", "--show-current")
        self.original_head = self.run_git("rev-parse", "HEAD")

    def run_git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True, text=True, check=True,
        ).stdout.strip()

    def invoke(self, *args, title="Fix login", env=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, {**ENV, **(env or {})}, clear=True), patch(
                "jira_branch.fetch_title", return_value=title
            ) as fetch, patch(
                "jira_branch.current_username", return_value="mariusgreve"
            ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = jira_branch.main(list(args))
        finally:
            os.chdir(previous)
        return result, stdout.getvalue(), stderr.getvalue(), fetch

    def test_create_switch_and_preserve_changes(self):
        (self.root / "work.txt").write_text("unfinished work")
        result, stdout, stderr, _ = self.invoke("PROJ-123", "--prefix", "feature")
        self.assertEqual(result, 0, stderr)
        self.assertIn("mariusgreve/feature/PROJ-123/fix-login", stdout)
        self.assertEqual(self.run_git("branch", "--show-current"), "mariusgreve/feature/PROJ-123/fix-login")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), self.original_head)
        self.assertEqual((self.root / "work.txt").read_text(), "unfinished work")

    def test_without_prefix(self):
        result, _, stderr, _ = self.invoke("PROJ-123")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.run_git("branch", "--show-current"), "mariusgreve/PROJ-123/fix-login")

    def test_ticket_key_is_normalized_to_uppercase(self):
        for key in ("proj-123", "PrOj-123"):
            with self.subTest(key=key):
                result, _, stderr, fetch = self.invoke(key)
                self.assertEqual(result, 0, stderr)
                fetch.assert_called_once_with(
                    "PROJ-123", "https://jira.example.com/jira", ENV["JIRA_TOKEN"]
                )
                self.assertEqual(self.run_git("branch", "--show-current"), "mariusgreve/PROJ-123/fix-login")
                self.run_git("switch", self.original_branch)
                self.run_git("branch", "-D", "mariusgreve/PROJ-123/fix-login")

    def test_environment_prefix(self):
        result, _, stderr, _ = self.invoke(
            "PROJ-123", env={"JIRA_BRANCH_PREFIX": "users/alice"}
        )
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.run_git("branch", "--show-current"), "mariusgreve/users/alice/PROJ-123/fix-login")

    def test_argument_overrides_environment_prefix(self):
        result, _, stderr, _ = self.invoke(
            "PROJ-123", "--prefix", "bugfix", env={"JIRA_BRANCH_PREFIX": "feature"}
        )
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.run_git("branch", "--show-current"), "mariusgreve/bugfix/PROJ-123/fix-login")

    def test_empty_argument_disables_environment_prefix(self):
        result, _, stderr, _ = self.invoke(
            "PROJ-123", "--prefix", "", env={"JIRA_BRANCH_PREFIX": "feature"}
        )
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.run_git("branch", "--show-current"), "mariusgreve/PROJ-123/fix-login")

    def test_existing_branch_is_not_overwritten(self):
        self.run_git("branch", "mariusgreve/PROJ-123/fix-login")
        result, stdout, stderr, _ = self.invoke("PROJ-123")
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertIn("already exists", stderr)
        self.assertEqual(self.run_git("branch", "--show-current"), self.original_branch)
        self.assertEqual(self.run_git("rev-parse", "mariusgreve/PROJ-123/fix-login"), self.original_head)

    def test_invalid_prefixes(self):
        for prefix in ("bad prefix", "/feature", "feature/", "bad..prefix", "a@{b"):
            with self.subTest(prefix=prefix):
                result, stdout, stderr, _ = self.invoke("PROJ-123", "--prefix=" + prefix)
                self.assertEqual(result, 1)
                self.assertEqual(stdout, "")
                self.assertIn("Git command failed", stderr)
                self.assertEqual(self.run_git("branch", "--show-current"), self.original_branch)

    def test_invalid_keys_do_not_fetch(self):
        for key in ("PROJ-0", "../PROJ-1", "PROJ.-123", "PROJ-1/title"):
            with self.subTest(key=key):
                result, _, stderr, fetch = self.invoke(key)
                self.assertEqual(result, 1)
                self.assertIn("Invalid ticket key", stderr)
                fetch.assert_not_called()

    def test_fetch_failure_does_not_create_branch(self):
        with patch("jira_branch.fetch_title", side_effect=jira_branch.BranchError("Jira denied access")):
            with patch.object(jira_branch, "configuration", return_value=("https://jira.example.com", "token")):
                previous = Path.cwd()
                try:
                    os.chdir(self.root)
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(jira_branch.main(["PROJ-123"]), 1)
                finally:
                    os.chdir(previous)
        self.assertEqual(self.run_git("branch", "--format=%(refname:short)"), self.original_branch)

    def test_token_in_prefix_is_rejected(self):
        result, stdout, stderr, _ = self.invoke("PROJ-123", "--prefix", ENV["JIRA_TOKEN"])
        self.assertEqual(result, 1)
        self.assertEqual(stdout, "")
        self.assertNotIn(ENV["JIRA_TOKEN"], stderr)
        self.assertEqual(self.run_git("branch", "--show-current"), self.original_branch)


class GitErrorTests(unittest.TestCase):
    @patch("jira_branch.subprocess.run", side_effect=FileNotFoundError())
    def test_missing_git(self, run):
        with self.assertRaisesRegex(jira_branch.BranchError, "installed"):
            jira_branch.git("status")

    @patch("jira_branch.subprocess.run")
    def test_git_failure(self, run):
        run.return_value = MagicMock(returncode=1, stderr="not a git repository", stdout="")
        with self.assertRaisesRegex(jira_branch.BranchError, "not a git repository"):
            jira_branch.git("rev-parse", "--is-inside-work-tree")


if __name__ == "__main__":
    unittest.main()
