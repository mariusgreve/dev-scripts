# dev-scripts

## Create a branch from a Jira ticket

`jira_branch.py` creates a branch from the current commit and switches to it.
Run it inside the Git repository where you want the branch. Requires Python 3
and Git 2.23 or newer, plus the `whoami` command.

Set `JIRA_BASE_URL` to the Jira server's base URL and `JIRA_TOKEN` to a
personal access token with permission to view the ticket. The script
authenticates with the token as a bearer token:

```sh
export JIRA_BASE_URL="https://jira.example.com"
export JIRA_TOKEN="<your-personal-access-token>"

python3 /path/to/dev-scripts/jira_branch.py PROJ-123 --prefix feature
# Creates and switches to: <username>/feature/PROJ-123/ticket-title-slug

python3 /path/to/dev-scripts/jira_branch.py PROJ-123
# Creates and switches to: <username>/PROJ-123/ticket-title-slug

export JIRA_BRANCH_PREFIX="feature"
python3 /path/to/dev-scripts/jira_branch.py PROJ-123
# Creates and switches to: <username>/feature/PROJ-123/ticket-title-slug

python3 /path/to/dev-scripts/jira_branch.py PROJ-123 --prefix bugfix
# Overrides the environment prefix: <username>/bugfix/PROJ-123/ticket-title-slug
```

The script runs `whoami` and removes every character except ASCII letters and
digits from its output before using it as the first branch segment. `--prefix`
takes precedence over `JIRA_BRANCH_PREFIX` and, when set, is added after the
username. Use `--prefix ""` to omit an environment-configured prefix for one
invocation; the username segment is always included.

Ticket keys may be entered in lowercase, uppercase, or mixed case; the script
converts them to uppercase before requesting the Jira ticket and naming the
branch. The optional prefix may contain path segments,
such as `users/alice`, but must not have a leading or trailing slash. The title
is normalized to lowercase ASCII (American Standard Code for Information
Interchange), with punctuation and whitespace replaced by hyphens; decomposable
accents are removed. A title with no remaining letters or digits is rejected.
Git validates the complete branch name before creation.

The script reads only the ticket summary through the Jira Data Center/Server
REST (Representational State Transfer) API (Application Programming Interface)
version 2. It does not modify Jira, fetch remote Git branches, push, commit,
stash changes, or overwrite an existing branch. Uncommitted changes are left
in place; Git refuses the switch if it cannot preserve them. A repository must
already have at least one commit.

The Jira address must use HTTPS (Hypertext Transfer Protocol Secure); plain
HTTP (Hypertext Transfer Protocol) is allowed only for loopback testing.
Certificate verification remains enabled and redirects are refused to protect
the token. Configuration, Jira and Git failures print an error to standard error
and exit with status 1 without claiming success.

Run the local tests without Jira credentials or network access to Jira:

```sh
python3 -m unittest discover -s tests -v
```
