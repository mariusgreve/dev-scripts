#!/usr/bin/env python3
"""Export Bitbucket Server/Data Center pull request data to local files."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from bitbucket_client import (
    BitbucketError,
    bitbucket_token,
    fetch_pull_request,
    parse_git_remote,
    parse_pull_request_url,
    validate_base_url,
)


def git_remote_url(remote):
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        raise BitbucketError("Could not run Git. Check that Git is installed and available.") from None
    if result.returncode:
        raise BitbucketError(
            f"Could not read Git remote {remote!r}. Run this command in a Git repository "
            "or provide a pull request URL."
        )
    return result.stdout.strip()


def resolve_pull_request(value, remote):
    if re.fullmatch(r"[1-9][0-9]*", value):
        base_url, project, repository = parse_git_remote(git_remote_url(remote))
        configured_base_url = os.environ.get("BITBUCKET_BASE_URL")
        if configured_base_url:
            base_url = validate_base_url(configured_base_url)
        return base_url, project, repository, int(value)
    if value.startswith(("https://", "http://")):
        return parse_pull_request_url(value)
    raise BitbucketError(
        "Provide a positive pull request number or a Bitbucket Server/Data Center pull request URL."
    )


def export_files(destination, source_url, project, repository, pull_request_id, data, token):
    files = {
        "pull-request.json": json.dumps(data["pull_request"], ensure_ascii=False, indent=2) + "\n",
        "commits.json": json.dumps(data["commits"], ensure_ascii=False, indent=2) + "\n",
        "changes.json": json.dumps(data["changes"], ensure_ascii=False, indent=2) + "\n",
        "activities.json": json.dumps(data["activities"], ensure_ascii=False, indent=2) + "\n",
        "diff.patch": data["diff"],
    }
    if any(token in contents for contents in files.values()):
        raise BitbucketError("Bitbucket response contains the configured token; refusing to export.")

    manifest = {
        "source_url": source_url,
        "project": project,
        "repository": repository,
        "pull_request_id": pull_request_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            "pull-request.json": "Complete pull request response, including participants and properties.",
            "commits.json": f"All paginated commits ({len(data['commits'])}).",
            "changes.json": f"All paginated changed paths ({len(data['changes'])}).",
            "activities.json": f"All paginated activities, including comments and review events ({len(data['activities'])}).",
            "diff.patch": "Pull request diff as returned by the Bitbucket REST API.",
        },
    }
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if any(token in contents for contents in files.values()):
        raise BitbucketError("Bitbucket response contains the configured token; refusing to export.")

    destination = Path(destination)
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise BitbucketError(f"Output path already exists; refusing to overwrite: {destination}")

    created_destination = False
    try:
        with tempfile.TemporaryDirectory(prefix=f".{destination.name}.", dir=parent) as temporary:
            staging = Path(temporary)
            for name, contents in files.items():
                (staging / name).write_text(contents, encoding="utf-8")
            destination.mkdir()
            created_destination = True
            for path in staging.iterdir():
                path.replace(destination / path.name)
    except OSError as exc:
        if created_destination:
            shutil.rmtree(destination)
        raise BitbucketError(f"Could not write pull request export: {exc}") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pull_request",
        help="Pull request number (uses the Git remote) or complete Bitbucket PR URL",
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to use when given a pull request number (default: origin)",
    )
    parser.add_argument(
        "--output",
        help="Output directory (default: bitbucket-pr-<project>-<repository>-<id>)",
    )
    args = parser.parse_args(argv)
    try:
        token = bitbucket_token()
        base_url, project, repository, pull_request_id = resolve_pull_request(
            args.pull_request, args.remote
        )
        source_url = (
            f"{base_url}/projects/{project}/repos/{repository}/pull-requests/{pull_request_id}"
        )
        destination = args.output or (
            f"bitbucket-pr-{project}-{repository}-{pull_request_id}"
        )
        data = fetch_pull_request(
            base_url, project, repository, pull_request_id, token
        )
        export_files(
            destination, source_url, project, repository, pull_request_id, data, token
        )
    except BitbucketError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Saved pull request data to: {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
