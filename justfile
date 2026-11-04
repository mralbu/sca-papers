base_url := "https://www.jgmaas.com/SCA/"
papers_dir := "papers"
duplicates := "duplicates.txt"

# List available recipes
default:
    @just --list

# Download SCA papers, or update an existing download (only new/changed files are fetched; known duplicates are skipped)
download:
    #!/usr/bin/env bash
    set -euo pipefail
    # Exclude query-string sort links and every file listed in {{duplicates}}.
    reject='\?'
    if [ -s "{{duplicates}}" ]; then
        dup_re=$(sed -e 's/[.]/\\./g' -e 's|^|/|' -e 's|$|$|' "{{duplicates}}" | paste -sd'|')
        reject="$reject|$dup_re"
    fi
    wget --mirror --no-parent --no-host-directories --cut-dirs=1 \
        --accept pdf --reject-regex "$reject" \
        --execute robots=off --wait=0.2 --random-wait \
        --no-verbose --directory-prefix={{papers_dir}} \
        {{base_url}}
    echo "$(find {{papers_dir}} -name '*.pdf' | wc -l) PDFs in {{papers_dir}}/"

alias update := download

# Delete duplicate PDFs (1-page "Click here to download" previews that sit next to a full "1-<name>" copy) and record them in duplicates.txt. Pass "dry-run" to only list them.
dedup mode="delete":
    #!/usr/bin/env bash
    set -euo pipefail
    found=$(mktemp)
    trap 'rm -f "$found"' EXIT
    for f in {{papers_dir}}/*/*.pdf; do
        name=$(basename "$f"); dir=$(dirname "$f")
        case "$name" in 1-*) continue ;; esac
        [ -f "$dir/1-$name" ] || continue
        # Capture first, then match: `pdftotext | grep -q` can SIGPIPE under pipefail.
        first_page=$(pdftotext -l 1 "$f" - 2>/dev/null || true)
        if [[ "$first_page" == *"Click here to download the complete version"* ]]; then
            echo "${f#{{papers_dir}}/}" >> "$found"
        fi
    done
    n=$(wc -l < "$found")
    if [ "{{mode}}" = "dry-run" ]; then
        cat "$found"; echo "$n duplicate(s) found (dry run, nothing deleted)"; exit 0
    fi
    [ "{{mode}}" = "delete" ] || { echo "unknown mode '{{mode}}' (use delete or dry-run)" >&2; exit 1; }
    while read -r rel; do rm -v -- "{{papers_dir}}/$rel"; done < "$found"
    # Keep the list cumulative so download keeps skipping files deleted earlier.
    touch "{{duplicates}}"
    sort -u "{{duplicates}}" "$found" -o "{{duplicates}}"
    echo "$n duplicate(s) deleted; $(wc -l < "{{duplicates}}") listed in {{duplicates}}"
