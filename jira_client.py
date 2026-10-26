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
    if not re.fullmatch(r"[!-~]+", token):
        raise JiraError("JIRA_TOKEN must contain only visible ASCII characters without spaces.")
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

