# dev-scripts

## Install

```sh
./install.sh
```

Creates `~/.local/bin/create-branch` as a symbolic link to `create_branch.py`.
Existing files are not overwritten. Keep this repository in place and make sure
`~/.local/bin` is on your `PATH`, then run:

```sh
create-branch "update readme"
```

## Create a branch

`create_branch.py` creates and switches to a branch from a message or Jira ticket.
Run it inside a Git repository with at least one commit. Requires Python 3,
Git 2.23 or newer, and `whoami`.

```sh
python3 /path/to/dev-scripts/create_branch.py "update readme"
# <username>/update-readme

python3 /path/to/dev-scripts/create_branch.py "PROJ-123 update readme"
# <username>/PROJ-123/update-readme

python3 /path/to/dev-scripts/create_branch.py PROJ-123
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
The script only reads its title and does not modify Jira.

### Optional prefix

Add a prefix after the username with `--prefix`:

```sh
python3 /path/to/dev-scripts/create_branch.py "update readme" --prefix feature
# <username>/feature/update-readme
```

Set `JIRA_BRANCH_PREFIX` for a default prefix. `--prefix` overrides it;
`--prefix ""` omits it.

## Tests

Run locally without Jira credentials or access to Jira:

```sh
python3 -m unittest discover -s tests -v
```
