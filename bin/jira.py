#!/usr/bin/env python3
"""Open a Jira ticket in the default browser."""

import argparse
import re
import sys
import webbrowser

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from jira_client import JiraError, jira_base_url


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticket", help="Jira ticket key, for example PROJ-123")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-[1-9][0-9]*", args.ticket):
            raise JiraError("Provide a valid Jira ticket key, for example PROJ-123.")
        base_url = jira_base_url()
        url = f"{base_url}/browse/{args.ticket.upper()}"
        try:
            opened = webbrowser.open(url)
        except (webbrowser.Error, OSError):
            raise JiraError("Could not open the Jira ticket in the default browser.") from None
        if not opened:
            raise JiraError("Could not open the Jira ticket in the default browser.")
    except JiraError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
