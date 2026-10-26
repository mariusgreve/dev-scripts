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

    # Replace only links to our source script or wrappers installed by this script.
    if [ -L "$destination" ]; then
        if [ "$(readlink "$destination")" != "$source_path" ]; then
            printf 'Error: %s already points elsewhere\n' "$destination" >&2
            exit 1
        fi
        rm "$destination"
    elif [ -e "$destination" ]; then
        if ! grep -Fqx '# installed by dev-scripts/install.sh' "$destination" 2>/dev/null || \
           ! grep -Fqx "# source: $source_path" "$destination" 2>/dev/null; then
            printf 'Error: %s already exists\n' "$destination" >&2
            exit 1
        fi
    fi

    # Shell launchers work even if the Python source is not executable.
    temp="$destination.tmp.$$"
    trap 'rm -f "$temp"' EXIT HUP INT TERM
    printf '#!/bin/sh\n# installed by dev-scripts/install.sh\n# source: %s\nexec python3 "%s" "$@"\n' \
        "$source_path" "$source_path" > "$temp"
    chmod 755 "$temp"
    mv -f "$temp" "$destination"
    trap - EXIT HUP INT TERM
    printf 'Installed %s\n' "$destination"
done

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add %s to your PATH if commands are not found.\n' "$bin_dir" ;;
esac
