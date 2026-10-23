#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination="$HOME/.local/bin/create-branch"

if [ -e "$destination" ] || [ -L "$destination" ]; then
    printf 'Already exists: %s\n' "$destination" >&2
    exit 1
fi

mkdir -p "$HOME/.local/bin"
ln -s "$script_dir/create_branch.py" "$destination"
