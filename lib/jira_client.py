"""Shared Jira Server/Data Center API access for developer scripts."""

from http.client import HTTPException
import json
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

class JiraError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirected endpoint.
        return None


def configuration():
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    token = os.environ.get("JIRA_TOKEN", "")
    if not base_url or not token:
        raise JiraError("Set JIRA_BASE_URL and JIRA_TOKEN before fetching a ticket.")
    base_url = jira_base_url()
    if not re.fullmatch(r"[!-~]+", token):
        raise JiraError("JIRA_TOKEN must contain only visible ASCII characters without spaces.")
    return base_url, token


def jira_base_url():
    base_url = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    if not base_url:
        raise JiraError("Set JIRA_BASE_URL before opening a Jira ticket.")
    try:
        address = urlsplit(base_url)
        port = address.port
    except ValueError:
        raise JiraError("JIRA_BASE_URL must be a valid Jira base address.") from None
    if (
        not address.hostname
        or address.username is not None
        or address.password is not None
        or "?" in base_url
        or "#" in base_url
        or re.search(r"[\s\\]", base_url)
        or port == 0
    ):
        raise JiraError(
            "JIRA_BASE_URL must be a Jira base address without credentials, query or fragment."
        )
    if address.scheme != "https" and not (
        address.scheme == "http" and address.hostname in {"127.0.0.1", "::1", "localhost"}
    ):
        raise JiraError(
            "JIRA_BASE_URL must use https:// (http:// is allowed only for loopback testing)."
        )
    return base_url


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
        raise JiraError(message) from None
    except (URLError, OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, TimeoutError):
            message = "Jira request timed out."
        elif isinstance(reason, ssl.SSLError):
            message = "Jira certificate verification or secure connection failed. Check the trusted certificates."
        else:
            message = "Could not connect to Jira. Check the base address and network access."
        raise JiraError(message) from None
    try:
        issue = json.loads(data)
    except (ValueError, UnicodeError):
        raise JiraError("Jira returned invalid JSON instead of a ticket response.") from None
    if (
        not isinstance(issue, dict)
        or issue.get("key") != key
        or not isinstance(issue.get("fields"), dict)
    ):
        raise JiraError("Jira returned an unexpected ticket key or missing fields.")
    title = issue["fields"].get("summary")
    if not isinstance(title, str) or not title.strip():
        raise JiraError("Jira returned a missing or empty ticket title.")
    if token in title:
        raise JiraError("Jira title contains the configured token; refusing to use it.")
    return title


def search_issues(jql, base_url, token, *, max_results=100, page_size=50):
    """Read at most max_results matching issues using Jira REST API v2."""
    if not isinstance(jql, str) or not jql.strip():
        raise JiraError("Provide a non-empty JQL query.")
    if not isinstance(max_results, int) or isinstance(max_results, bool) or not 1 <= max_results <= 1000:
        raise JiraError("max_results must be between 1 and 1000.")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 100:
        raise JiraError("page_size must be between 1 and 100.")

    fields = "summary,description,status,priority,issuetype,assignee,labels,updated,created,duedate,issuelinks,subtasks,parent,timetracking,timeestimate"
    issues = []
    while len(issues) < max_results:
        requested = min(page_size, max_results - len(issues))
        params = urlencode({
            "jql": jql, "startAt": len(issues), "maxResults": requested,
            "fields": fields,
        })
        request = Request(
            base_url + "/rest/api/2/search?" + params,
            headers={"Accept": "application/json", "Authorization": "Bearer " + token},
            method="GET",
        )
        try:
            with build_opener(NoRedirects()).open(request, timeout=30) as response:
                data = response.read()
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if 300 <= code < 400:
                raise JiraError("Jira redirected the request; redirects are disabled. Check JIRA_BASE_URL.") from None
            raise JiraError(f"Jira search failed with HTTP status {code}.") from None
        except (URLError, OSError, HTTPException) as exc:
            reason = exc.reason if isinstance(exc, URLError) else exc
            if isinstance(reason, TimeoutError):
                message = "Jira request timed out."
            elif isinstance(reason, ssl.SSLError):
                message = "Jira certificate verification or secure connection failed."
            else:
                message = "Could not connect to Jira. Check the base address and network access."
            raise JiraError(message) from None
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            raise JiraError("Jira returned invalid JSON from search.") from None
        if (not isinstance(result, dict) or not isinstance(result.get("issues"), list)
                or not isinstance(result.get("total"), int)):
            raise JiraError("Jira returned an unexpected search response.")
        batch = result["issues"]
        if len(batch) > requested:
            raise JiraError("Jira returned more issues than requested.")
        if any(not isinstance(item, dict) or not isinstance(item.get("key"), str)
               or not isinstance(item.get("fields"), dict) for item in batch):
            raise JiraError("Jira returned an invalid issue.")
        issues.extend(batch)
        if not batch or len(issues) >= result["total"]:
            break
    return issues
