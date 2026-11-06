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

# --- Pipeline (each stage is resumable: re-runs only process new/changed papers) ---

# Install/sync the Python environment
setup:
    uv sync

# Stage 0: list papers with their IDs and source URLs (data/inventory.json)
inventory:
    uv run sca inventory

# Stage 1: convert PDFs to markdown with marker (data/markdown/<id>/). Args: paper IDs, --workers N, --limit N
convert *args:
    uv run sca convert {{args}}

# Stage 2: rule-based metadata (title, authors, abstract, references) -> data/metadata/. Args: paper IDs (prints them), --force
metadata *args:
    uv run sca metadata {{args}}

# Stage 3: embeddings -> data/embeddings/<model>/. Args: model names (bge-m3, specter2), --compare
embed *args:
    uv run sca embed {{args}}

# Stage 4: 2D map + topics -> data/topics/topics.json (hand overrides in topics.yaml). Args: --model M, --force
topics *args:
    uv run sca topics {{args}}

# Stage 5: citation graph + importance (cited_by, PageRank) -> data/citations/. Args: --force
citations *args:
    uv run sca citations {{args}}

# Stage 6: figure index + one WebP thumbnail per paper -> data/figures/, site/data/figures/. Args: --force
figures *args:
    uv run sca figures {{args}}

# Stage 7: export site/data/ (papers.json, topics.json) from the stage outputs; commit it to publish
site-data:
    uv run sca site

# Phase 2: LLM summaries/metadata/figure picks -> data/llm/<model>/ (Claude API; costs money). Args: paper IDs (default: the 20-paper sample), --models haiku sonnet, --force
summarize *args:
    uv run sca summarize {{args}}

# Run every stage after convert, in order (each is cached/resumable)
build: metadata embed topics citations figures site-data

# Serve the site on all interfaces (port 8000) and print the LAN URL
serve port="8000":
    #!/usr/bin/env bash
    set -euo pipefail
    # LAN IP: macOS (default-route interface) or Linux (hostname -I).
    ip=""
    if command -v ipconfig >/dev/null 2>&1; then
        iface=$(route -n get default 2>/dev/null | awk '/interface:/ {print $2}')
        [ -n "$iface" ] && ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
    fi
    [ -z "$ip" ] && ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)
    echo "Local:   http://localhost:{{port}}"
    echo "Network: http://${ip:-unknown-ip}:{{port}}"
    # no-cache: browsers revalidate on every load, so edits to site/ show up on a normal reload.
    exec python3 -c 'import functools, http.server as h, sys
    class H(h.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()
    h.ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1])), functools.partial(H, directory="site")).serve_forever()' {{port}}

# Run tests and lint
check:
    uv run pytest -q
    uv run ruff check src tests
    uv run ruff format --check src tests
