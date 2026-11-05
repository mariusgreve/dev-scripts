"""Read pull request data from Bitbucket Server/Data Center."""

from http.client import HTTPException
import json
import os
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class BitbucketError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def bitbucket_token():
    token = os.environ.get("BITBUCKET_TOKEN", "")
    if not token:
        raise BitbucketError("Set BITBUCKET_TOKEN to a Bitbucket personal access token.")
    if not re.fullmatch(r"[!-~]+", token):
        raise BitbucketError("BITBUCKET_TOKEN must contain visible ASCII characters without spaces.")
    return token


def validate_base_url(base_url):
    base_url = base_url.rstrip("/")
    try:
        address = urlsplit(base_url)
        port = address.port
    except ValueError:
        raise BitbucketError("Bitbucket base URL must be a valid address.") from None
    if (
        not address.hostname
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
        or re.search(r"[\s\\]", base_url)
        or port == 0
    ):
        raise BitbucketError(
            "Bitbucket base URL must not contain credentials, query or fragment."
        )
    if address.scheme != "https" and not (
        address.scheme == "http" and address.hostname in {"127.0.0.1", "::1", "localhost"}
    ):
        raise BitbucketError(
            "Bitbucket base URL must use https:// (http:// is allowed only for loopback testing)."
        )
    return base_url


def parse_pull_request_url(url):
    try:
        address = urlsplit(url)
        port = address.port
    except (TypeError, ValueError):
        raise BitbucketError("Provide a valid Bitbucket pull request URL.") from None
    match = re.search(
        r"/projects/([^/]+)/repos/([^/]+)/pull-requests/([1-9][0-9]*)(?:/|$)",
        address.path,
    )
    if (
        address.scheme not in {"https", "http"}
        or not address.hostname
        or address.username is not None
        or address.password is not None
        or port == 0
        or match is None
    ):
        raise BitbucketError(
            "URL must be a Bitbucket Server/Data Center pull request URL."
        )
    base_path = address.path[:match.start()].rstrip("/")
    base_url = urlunsplit((address.scheme, address.netloc, base_path, "", ""))
    base_url = validate_base_url(base_url)
    project, repository, pull_request_id = (
        match.group(1), match.group(2), int(match.group(3))
    )
    return base_url, project, repository, pull_request_id


def parse_git_remote(remote_url):
    """Return the REST base URL and repository coordinates from a Bitbucket remote."""
    try:
        address = urlsplit(remote_url)
    except ValueError:
        address = None

    if address and address.scheme in {"https", "http"}:
        if not address.hostname or address.username is not None or address.password is not None:
            raise BitbucketError("Git remote URL must not contain credentials.")
        host = address.netloc
        path = address.path
        scheme = address.scheme
    elif address and address.scheme == "ssh":
        if not address.hostname:
            raise BitbucketError("Could not read the host from the Git remote URL.")
        # SSH ports are not necessarily the port used by the Bitbucket REST service.
        host = address.hostname
        scheme = "https"
        path = address.path
    else:
        match = re.fullmatch(r"(?:[^@/]+@)?([^:/]+):(.+)", remote_url or "")
        if not match:
            raise BitbucketError(
                "Could not read a Bitbucket repository from the Git remote URL."
            )
        host, path = match.groups()
        scheme = "https"

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise BitbucketError("Git remote URL must include a Bitbucket project and repository.")
    repository = re.sub(r"\.git$", "", parts[-1])
    project = parts[-2]
    if not project or not repository:
        raise BitbucketError("Git remote URL must include a Bitbucket project and repository.")

    if "scm" in parts[:-2]:
        context_path = "/" + "/".join(parts[:parts.index("scm") + 1])
    else:
        context_path = "/" + "/".join(parts[:-2]) if len(parts) > 2 else ""
    base_url = validate_base_url(f"{scheme}://{host}{context_path}")
    return base_url, project, repository


def _request(base_url, endpoint, token, accept):
    request = Request(
        base_url + endpoint,
        headers={"Accept": accept, "Authorization": "Bearer " + token},
        method="GET",
    )
    try:
        with build_opener(NoRedirects()).open(request, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if 300 <= code < 400:
            message = "Bitbucket redirected the request; redirects are disabled. Check the URL."
        elif code == 401:
            message = "Bitbucket rejected authentication (401). Check BITBUCKET_TOKEN."
        elif code == 403:
            message = "Bitbucket denied access (403). Check the token's permissions."
        elif code == 404:
            message = "Bitbucket pull request or endpoint not found (404). Check the URL and access."
        else:
            message = f"Bitbucket request failed with HTTP status {code}."
        raise BitbucketError(message) from None
    except (URLError, OSError, HTTPException) as exc:
        reason = exc.reason if isinstance(exc, URLError) else exc
        if isinstance(reason, TimeoutError):
            message = "Bitbucket request timed out."
        elif isinstance(reason, ssl.SSLError):
            message = "Bitbucket certificate verification or secure connection failed."
        else:
            message = "Could not connect to Bitbucket. Check the URL and network access."
        raise BitbucketError(message) from None


def _json_request(base_url, endpoint, token):
    data = _request(base_url, endpoint, token, "application/json")
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError):
        raise BitbucketError("Bitbucket returned invalid JSON.") from None
    if not isinstance(result, dict):
        raise BitbucketError("Bitbucket returned an unexpected JSON response.")
    return result


def paginated_values(base_url, endpoint, token, *, page_size=100):
    values = []
    start = 0
    while True:
        separator = "&" if "?" in endpoint else "?"
        page = _json_request(
            base_url,
            f"{endpoint}{separator}{urlencode({'start': start, 'limit': page_size})}",
            token,
        )
        batch = page.get("values")
        if not isinstance(batch, list) or not isinstance(page.get("isLastPage"), bool):
            raise BitbucketError("Bitbucket returned an invalid paginated response.")
        values.extend(batch)
        if page["isLastPage"]:
            return values
        next_start = page.get("nextPageStart")
        if not isinstance(next_start, int) or isinstance(next_start, bool) or next_start <= start:
            raise BitbucketError("Bitbucket returned invalid pagination metadata.")
        start = next_start


def fetch_pull_request(base_url, project, repository, pull_request_id, token):
    base_url = validate_base_url(base_url)
    project_path = quote(project, safe="")
    repository_path = quote(repository, safe="")
    root = (
        f"/rest/api/1.0/projects/{project_path}/repos/{repository_path}"
        f"/pull-requests/{pull_request_id}"
    )
    details = _json_request(base_url, root, token)
    commits = paginated_values(base_url, root + "/commits", token)
    changes = paginated_values(base_url, root + "/changes", token)
    activities = paginated_values(base_url, root + "/activities", token)
    try:
        diff = _request(base_url, root + "/diff", token, "text/plain").decode("utf-8")
    except UnicodeError:
        raise BitbucketError("Bitbucket returned a diff that is not valid UTF-8.") from None
    return {
        "pull_request": details,
        "commits": commits,
        "changes": changes,
        "activities": activities,
        "diff": diff,
    }
