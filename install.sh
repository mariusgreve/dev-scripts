#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
bin_dir="$HOME/.local/bin"
mkdir -p "$bin_dir"

found=0
for source in "$script_dir"/bin/*.py; do
    [ -f "$source" ] && [ -x "$source" ] || continue
    found=1
    name=$(basename "$source" .py | tr '_' '-')
    destination="$bin_dir/$name"

    if [ -L "$destination" ]; then
        if [ "$(readlink "$destination")" != "$source" ]; then
            printf 'Error: %s points elsewhere\n' "$destination" >&2
            exit 1
        fi
        printf 'Already installed: %s\n' "$name"
        continue
    fi
    if [ -e "$destination" ]; then
        printf 'Error: %s already exists\n' "$destination" >&2
        exit 1
    fi
    ln -s "$source" "$destination"
    printf 'Installed: %s -> %s\n' "$name" "$source"
done

[ "$found" -eq 1 ] || {
    printf 'Error: no executable Python scripts found in bin/\n' >&2
    exit 1
}

case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) printf 'Add %s to PATH if commands are not found.\n' "$bin_dir" ;;
esac
