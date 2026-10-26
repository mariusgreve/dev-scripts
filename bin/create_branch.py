#!/usr/bin/env python3
"""Create and switch to a Git branch from a message or Jira ticket."""

import argparse
import os

import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", "lib"))

from jira_client import JiraError as BranchError, configuration, fetch_title
import re
import subprocess
import sys
import unicodedata



def branch_name(key, title, prefix):
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    if not slug:
        raise BranchError("Branch title cannot produce a non-empty ASCII branch slug.")
    return "/".join(part for part in (prefix, key, slug) if part)


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


def current_username():
    try:
        result = subprocess.run(["whoami"], capture_output=True, text=True, check=False)
    except OSError:
        raise BranchError("Could not run whoami to determine the current username.") from None
    if result.returncode:
        raise BranchError("Could not determine the current username with whoami.")
    username = re.sub(r"[^A-Za-z0-9]", "", result.stdout.strip())
    if not username:
        raise BranchError("Current username must contain at least one letter or digit.")
    return username


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Create and switch to a branch from the current commit using a message "
            "or Jira ticket. Only a ticket key without a message requires "
            "JIRA_BASE_URL and JIRA_TOKEN."
        )
    )
    parser.add_argument(
        "message", nargs="+",
        help="Branch message, Jira ticket key, or ticket key followed by a message",
    )
    parser.add_argument(
        "--prefix",
        default=os.environ.get("JIRA_BRANCH_PREFIX", ""),
        help="Branch prefix, for example feature (overrides JIRA_BRANCH_PREFIX)",
    )
    args = parser.parse_args(argv)
    try:
        message = " ".join(args.message).strip()
        if not message:
            raise BranchError("Provide a branch message or Jira ticket key.")
        parts = message.split(maxsplit=1)
        key = ""
        title = message
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*", parts[0]):
            key = parts[0].upper()
            title = parts[1] if len(parts) > 1 else ""
        token = os.environ.get("JIRA_TOKEN", "")
        if key and not title:
            base_url, token = configuration()
        username = current_username()
        if git("rev-parse", "--is-inside-work-tree") != "true":
            raise BranchError("Run this script inside a Git working tree.")
        git("rev-parse", "--verify", "HEAD")
        if key and not title:
            title = fetch_title(key, base_url, token)
        if token and token in title:
            raise BranchError("Branch title contains the configured token; refusing to use it.")
        prefix = "/".join(part for part in (username, args.prefix) if part)
        name = branch_name(key, title, prefix)
        if token and token in name:
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
