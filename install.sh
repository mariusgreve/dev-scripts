#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bin_dir="$HOME/.local/bin"

command -v python3 >/dev/null 2>&1 || {
    printf 'Error: python3 is required\n' >&2
    exit 1
}

mkdir -p "$bin_dir"

for name in create-branch jira-backlog; do
    case "$name" in
        create-branch) script=create_branch.py ;;
        jira-backlog) script=jira_backlog.py ;;
    esac

    source_path="$script_dir/$script"
    destination="$bin_dir/$name"
    [ -f "$source_path" ] || {
        printf 'Error: missing %s\n' "$source_path" >&2
        exit 1
    }

    if [ -L "$destination" ]; then
        if [ "$(readlink "$destination")" != "$source_path" ]; then
            printf 'Error: %s already points elsewhere\n' "$destination" >&2
            exit 1
        fi
        printf 'Already installed: %s\n' "$destination"
        continue
    fi

    if [ -e "$destination" ]; then
        # Migrate wrappers created by the previous version of this installer.
        if grep -Fqx '# installed by dev-scripts/install.sh' "$destination" 2>/dev/null &&
           grep -Fqx "# source: $source_path" "$destination" 2>/dev/null; then
            rm "$destination"
        else
            printf 'Error: %s already exists\n' "$destination" >&2
            exit 1
        fi
    fi

    chmod +x "$source_path"
    ln -s "$source_path" "$destination"
    printf 'Installed %s -> %s\n' "$destination" "$source_path"
done

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add %s to your PATH if commands are not found.\n' "$bin_dir" ;;
esac
