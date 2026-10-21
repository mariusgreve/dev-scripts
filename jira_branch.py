#!/usr/bin/env python3
"""Create and switch to a Git branch named after a Jira ticket."""

import argparse
from http.client import HTTPException
import json
import os
import re
import ssl
import subprocess
import sys
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class BranchError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirected endpoint.
        return None


def configuration():
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    token = os.environ.get("JIRA_TOKEN", "")
    if not base_url or not token:
        raise BranchError("Set JIRA_BASE_URL and JIRA_TOKEN before fetching a ticket.")
    try:
        address = urlsplit(base_url)
        port = address.port
    except ValueError:
        raise BranchError("JIRA_BASE_URL must be a valid Jira base address.") from None
    if (
        not address.hostname
        or address.username is not None
        or address.password is not None
        or "?" in base_url
        or "#" in base_url
        or re.search(r"[\s\\]", base_url)
        or port == 0
    ):
        raise BranchError(
            "JIRA_BASE_URL must be a Jira base address without credentials, query or fragment."
        )
    if address.scheme != "https" and not (
        address.scheme == "http" and address.hostname in {"127.0.0.1", "::1", "localhost"}
    ):
        raise BranchError(
            "JIRA_BASE_URL must use https:// (http:// is allowed only for loopback testing)."
        )
    if not re.fullmatch(r"[!-~]+", token):
        raise BranchError("JIRA_TOKEN must contain only visible ASCII characters without spaces.")
    return base_url, token


def fetch_title(key, base_url, token):
    request = Request(
        base_url + "/rest/api/2/issue/" + key + "?" + urlencode({"fields": "summary"}),
        headers={"Accept": "application/json", "Authorization": "Bearer " + token},
        method="GET",
    )
    try:
        with build_opener(NoRedirects()).open(request, timeout=30) as response:
            data = response.read()
    except HTTPError as exc:
        messages = {
            401: "Jira rejected authentication (401). Check JIRA_TOKEN.",
            403: "Jira denied access (403). Check the token's permissions.",
            404: "Jira ticket or endpoint not found (404). Check the key, base address and access.",
        }
        if 300 <= exc.code < 400:
            message = "Jira redirected the request; redirects are disabled. Check JIRA_BASE_URL."
        else:
            message = messages.get(exc.code, f"Jira request failed with HTTP status {exc.code}.")
        exc.close()
        raise BranchError(message) from None
    except (URLError, OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, TimeoutError):
            message = "Jira request timed out."
        elif isinstance(reason, ssl.SSLError):
            message = "Jira certificate verification or secure connection failed. Check the trusted certificates."
        else:
            message = "Could not connect to Jira. Check the base address and network access."
        raise BranchError(message) from None
    try:
        issue = json.loads(data)
    except (ValueError, UnicodeError):
        raise BranchError("Jira returned invalid JSON instead of a ticket response.") from None
    if (
        not isinstance(issue, dict)
        or issue.get("key") != key
        or not isinstance(issue.get("fields"), dict)
    ):
        raise BranchError("Jira returned an unexpected ticket key or missing fields.")
    title = issue["fields"].get("summary")
    if not isinstance(title, str) or not title.strip():
        raise BranchError("Jira returned a missing or empty ticket title.")
    if token in title:
        raise BranchError("Jira title contains the configured token; refusing to use it.")
    return title


def branch_name(key, title, prefix):
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        raise BranchError("Ticket title cannot produce a non-empty ASCII branch slug.")
    return f"{prefix}/{key}/{slug}" if prefix else f"{key}/{slug}"


def git(*args):
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
    except OSError:
        raise BranchError("Could not run Git. Check that Git is installed and available.") from None
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise BranchError(f"Git command failed: {detail or 'no error details available'}")
    return result.stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Create and switch to a branch from the current commit using a Jira ticket. "
            "Requires JIRA_BASE_URL and JIRA_TOKEN."
        )
    )
    parser.add_argument("key", help="Jira ticket key, for example PROJ-123")
    parser.add_argument(
        "--prefix",
        default=os.environ.get("JIRA_BRANCH_PREFIX", ""),
        help="Branch prefix, for example feature (overrides JIRA_BRANCH_PREFIX)",
    )
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*", args.key):
            raise BranchError("Invalid ticket key. Expected a key such as PROJ-123.")
        key = args.key.upper()
        base_url, token = configuration()
        if git("rev-parse", "--is-inside-work-tree") != "true":
            raise BranchError("Run this script inside a Git working tree.")
        git("rev-parse", "--verify", "HEAD")
        title = fetch_title(key, base_url, token)
        name = branch_name(key, title, args.prefix)
        if token in name:
            raise BranchError("Branch name contains the configured token; refusing to use it.")
        git("check-ref-format", "--branch", name)
        git("switch", "-c", name)
    except BranchError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Created and switched to branch: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
