import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

import bitbucket_client
import bitbucket_pr


TOKEN = "secret-test-token"


class RemoteParsingTests(unittest.TestCase):
    def test_pull_request_url_with_context_path(self):
        self.assertEqual(
            bitbucket_client.parse_pull_request_url(
                "https://bitbucket.example.com/bitbucket/projects/PROJ/"
                "repos/my-repo/pull-requests/123/overview"
            ),
            ("https://bitbucket.example.com/bitbucket", "PROJ", "my-repo", 123),
        )

    def test_rejects_non_server_pull_request_url(self):
        for url in (
            "https://bitbucket.org/workspace/repo/pull-requests/123",
            "https://bitbucket.example.com/projects/PROJ/repos/repo/pull-requests/0",
            "https://user:pass@bitbucket.example.com/projects/PROJ/repos/repo/pull-requests/1",
        ):
            with self.subTest(url=url), self.assertRaises(bitbucket_client.BitbucketError):
                bitbucket_client.parse_pull_request_url(url)

    def test_git_remote_formats(self):
        cases = [
            (
                "https://bitbucket.example.com/bitbucket/scm/PROJ/repo.git",
                ("https://bitbucket.example.com/bitbucket/scm", "PROJ", "repo"),
            ),
            (
                "ssh://git@bitbucket.example.com:7999/bitbucket/scm/PROJ/repo.git",
                ("https://bitbucket.example.com/bitbucket/scm", "PROJ", "repo"),
            ),
            (
                "git@bitbucket.example.com:PROJ/repo.git",
                ("https://bitbucket.example.com", "PROJ", "repo"),
            ),
        ]
        for remote, expected in cases:
            with self.subTest(remote=remote):
                self.assertEqual(bitbucket_client.parse_git_remote(remote), expected)

    @patch("bitbucket_pr.git_remote_url")
    def test_number_uses_git_remote_and_base_url_override(self, remote_url):
        remote_url.return_value = "https://bitbucket.example.com/scm/PROJ/repo.git"
        with patch.dict(os.environ, {"BITBUCKET_BASE_URL": "https://bb.example.com/bitbucket"}):
            self.assertEqual(
                bitbucket_pr.resolve_pull_request("123", "upstream"),
                ("https://bb.example.com/bitbucket", "PROJ", "repo", 123),
            )
        remote_url.assert_called_once_with("upstream")

    @patch("bitbucket_pr.git_remote_url")
    def test_url_does_not_depend_on_git_remote(self, remote_url):
        self.assertEqual(
            bitbucket_pr.resolve_pull_request(
                "https://bitbucket.example.com/bitbucket/projects/P/repos/R/pull-requests/42",
                "origin",
            ),
            ("https://bitbucket.example.com/bitbucket", "P", "R", 42),
        )
        remote_url.assert_not_called()


class ClientTests(unittest.TestCase):
    @patch("bitbucket_client._json_request")
    def test_paginates_all_values(self, request):
        request.side_effect = [
            {"values": [{"id": 1}, {"id": 2}], "isLastPage": False, "nextPageStart": 2},
            {"values": [{"id": 3}], "isLastPage": True},
        ]
        self.assertEqual(
            bitbucket_client.paginated_values("https://bitbucket.example.com", "/activities", TOKEN),
            [{"id": 1}, {"id": 2}, {"id": 3}],
        )
        self.assertIn("start=0&limit=100", request.call_args_list[0].args[1])
        self.assertIn("start=2&limit=100", request.call_args_list[1].args[1])

    @patch("bitbucket_client._request", return_value=b"diff --git a/file b/file\n")
    @patch("bitbucket_client.paginated_values")
    @patch("bitbucket_client._json_request")
    def test_fetches_pull_request_and_all_collections(self, details, pages, request):
        details.return_value = {"id": 123, "title": "Fix issue"}
        pages.side_effect = [[{"id": 1}], [{"path": "file"}], [{"action": "COMMENTED"}]]
        result = bitbucket_client.fetch_pull_request(
            "https://bitbucket.example.com/bitbucket", "PROJ", "repo", 123, TOKEN
        )
        self.assertEqual(result["pull_request"], details.return_value)
        self.assertEqual(result["commits"], [{"id": 1}])
        self.assertEqual(result["changes"], [{"path": "file"}])
        self.assertEqual(result["activities"], [{"action": "COMMENTED"}])
        self.assertTrue(result["diff"].startswith("diff --git"))
        root = "/rest/api/1.0/projects/PROJ/repos/repo/pull-requests/123"
        details.assert_called_once_with("https://bitbucket.example.com/bitbucket", root, TOKEN)
        self.assertEqual(
            [call.args[1] for call in pages.call_args_list],
            [root + "/commits", root + "/changes", root + "/activities"],
        )
        request.assert_called_once_with(
            "https://bitbucket.example.com/bitbucket", root + "/diff", TOKEN, "text/plain"
        )

    @patch("bitbucket_client._json_request")
    def test_rejects_invalid_pagination(self, request):
        request.return_value = {
            "values": [],
            "isLastPage": False,
            "nextPageStart": 0,
        }
        with self.assertRaisesRegex(bitbucket_client.BitbucketError, "pagination metadata"):
            bitbucket_client.paginated_values("https://bitbucket.example.com", "/commits", TOKEN)

    @patch("bitbucket_client._request", return_value=b"\xff")
    @patch("bitbucket_client.paginated_values", return_value=[])
    @patch("bitbucket_client._json_request", return_value={"id": 123})
    def test_rejects_non_utf8_diff(self, details, pages, request):
        with self.assertRaisesRegex(bitbucket_client.BitbucketError, "not valid UTF-8"):
            bitbucket_client.fetch_pull_request(
                "https://bitbucket.example.com", "PROJ", "repo", 123, TOKEN
            )


class ExportTests(unittest.TestCase):
    def make_data(self):
        return {
            "pull_request": {"id": 123, "title": "Fix issue"},
            "commits": [{"id": "abc"}],
            "changes": [{"path": "src/file.py"}],
            "activities": [{"action": "COMMENTED"}],
            "diff": "diff --git a/src/file.py b/src/file.py\n",
        }

    def test_exports_all_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "pr-review"
            bitbucket_pr.export_files(
                destination,
                "https://bitbucket.example.com/projects/PROJ/repos/repo/pull-requests/123",
                "PROJ",
                "repo",
                123,
                self.make_data(),
                TOKEN,
            )
            self.assertEqual(
                {path.name for path in destination.iterdir()},
                {
                    "pull-request.json",
                    "commits.json",
                    "changes.json",
                    "activities.json",
                    "diff.patch",
                    "manifest.json",
                },
            )
            commits = json.loads((destination / "commits.json").read_text())
            self.assertEqual(commits[0]["id"], "abc")
            manifest = json.loads((destination / "manifest.json").read_text())
            self.assertEqual(manifest["pull_request_id"], 123)
            self.assertIn("comments", manifest["files"]["activities.json"])

    def test_refuses_to_overwrite_and_never_exports_token(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "existing"
            destination.mkdir()
            sentinel = destination / "keep.txt"
            sentinel.write_text("keep")
            with self.assertRaisesRegex(bitbucket_client.BitbucketError, "already exists"):
                bitbucket_pr.export_files(destination, "", "P", "R", 1, self.make_data(), TOKEN)
            self.assertEqual(sentinel.read_text(), "keep")

            data = self.make_data()
            data["pull_request"]["title"] = TOKEN
            with self.assertRaisesRegex(bitbucket_client.BitbucketError, "contains the configured token"):
                bitbucket_pr.export_files(
                    Path(directory) / "secret",
                    "",
                    "P",
                    "R",
                    1,
                    data,
                    TOKEN,
                )
            self.assertFalse((Path(directory) / "secret").exists())

    @patch("bitbucket_pr.fetch_pull_request")
    @patch("bitbucket_pr.resolve_pull_request")
    def test_cli_writes_default_export(self, resolve, fetch):
        resolve.return_value = ("https://bitbucket.example.com", "PROJ", "repo", 123)
        fetch.return_value = self.make_data()
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"BITBUCKET_TOKEN": TOKEN}, clear=True
        ), contextlib.redirect_stdout(stdout):
            previous = Path.cwd()
            try:
                os.chdir(directory)
                self.assertEqual(bitbucket_pr.main(["123"]), 0)
            finally:
                os.chdir(previous)
            self.assertTrue((Path(directory) / "bitbucket-pr-PROJ-repo-123").is_dir())
        self.assertIn("Saved pull request data", stdout.getvalue())

    def test_missing_token_is_reported(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(stderr):
            self.assertEqual(bitbucket_pr.main(["123"]), 1)
        self.assertIn("BITBUCKET_TOKEN", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
