#!/bin/bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_command="${PYTHON:-python3}"
if [ -z "${PYTHON:-}" ] && [ -x "$script_dir/../.venv/bin/python" ]; then
    python_command="$script_dir/../.venv/bin/python"
fi

if [ "$#" -gt 0 ]; then
    exec "$python_command" "$script_dir/llm_extract.py" "$@"
fi

shopt -s nullglob
files=("$script_dir"/links/*.txt)
if [ "${#files[@]}" -eq 0 ]; then
    echo "No crawling/links/*.txt files found. Pass a .txt file or --url URL [--crawl-only]." >&2
    exit 1
fi

for file in "${files[@]}"; do
    "$python_command" "$script_dir/llm_extract.py" "$file"
done

echo "Finished processing all files"
