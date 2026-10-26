#!/usr/bin/env python3
"""Export a bounded Jira backlog as JSON for downstream analysis (read only)."""

import argparse
import json
import sys

from jira_client import JiraError, configuration, search_issues


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jql", required=True, help="JQL query identifying the relevant backlog")
    parser.add_argument("--limit", type=int, default=100, help="Maximum issues (1-1000, default 100)")
    parser.add_argument("--page-size", type=int, default=50, help="Issues per request (1-100)")
    args = parser.parse_args(argv)
    try:
        base_url, token = configuration()
        issues = search_issues(args.jql, base_url, token,
                               max_results=args.limit, page_size=args.page_size)
        # Do not echo authentication information even if mistakenly embedded in an issue.
        if any(token in json.dumps(issue, ensure_ascii=False) for issue in issues):
            raise JiraError("Jira response contains the configured token; refusing to export.")
        print(json.dumps({
            "jql": args.jql,
            "count": len(issues),
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    except JiraError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
