# dev-scripts

## Install

```sh
./install.sh
```

Installs `create-branch` and `jira-backlog` launchers in `~/.local/bin`.
Re-running the installer updates its launchers without overwriting unrelated commands.
Keep this repository in place and ensure `~/.local/bin` is on your `PATH`, then run:

```sh
create-branch "update readme"
jira-backlog --help
```

## Create a branch

`bin/create_branch.py` creates and switches to a branch from a message or Jira ticket.
Run it inside a Git repository with at least one commit. Requires Python 3,
Git 2.23 or newer, and `whoami`.

```sh
create-branch "update readme"
# <username>/update-readme

create-branch "PROJ-123 update readme"
# <username>/PROJ-123/update-readme

create-branch PROJ-123
# <username>/PROJ-123/ticket-title-slug (title fetched from Jira)
```

The username comes from `whoami`, with punctuation removed. Titles become
lowercase, hyphen-separated slugs, and ticket keys are converted to uppercase.
Uncommitted changes are preserved; existing branches are never overwritten.

### Jira setup

Only a ticket key **without a message** requires Jira configuration:

```sh
export JIRA_BASE_URL="https://jira.example.com"
export JIRA_TOKEN="<your-personal-access-token>"
```

Use a Jira Data Center/Server token with permission to view the ticket.
The shared `lib/jira_client.py` module handles Jira configuration, authentication,
HTTP requests and errors. `create-branch` uses it to read the ticket title
without modifying Jira.

### Optional prefix

Add a prefix after the username with `--prefix`:

```sh
create-branch "update readme" --prefix feature
# <username>/feature/update-readme
```

Set `JIRA_BRANCH_PREFIX` for a default prefix. `--prefix` overrides it;
`--prefix ""` omits it.

## Tests

Run locally without Jira credentials or access to Jira:

```sh
python3 -m unittest discover -s tests -v
```


## Export Jira backlog

`bin/jira_backlog.py` exports matching Jira Server/Data Center issues as JSON for
analysis by Copilot or other local tools. Requires the same `JIRA_BASE_URL`
and `JIRA_TOKEN` environment variables as `create_branch.py`.

```sh
jira-backlog --jql 'project = PROJ AND statusCategory != Done ORDER BY priority DESC' > backlog.json
jira-backlog --jql 'project = PROJ' --limit 50 --page-size 25
```

The script reads at most 100 issues by default (maximum 1000) and follows
Jira pagination. It exports standard issue fields including descriptions,
status, priority, issue links, estimates and dates. Jira project-specific
custom fields, including story points, may have different IDs.

It does not rank issues, modify Jira or call an AI model. Review and handle
exported data according to your organization's policies; avoid committing
backlog exports or sending internal issue contents to unapproved services.
