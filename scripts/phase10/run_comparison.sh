#!/bin/zsh
# Plan 10.2: the Claude in Chrome arm and the executor arm, alternating goal by goal, then the per-kind verdicts.
# The last 15 goals are round 2 (plan decision 9): 5 more per kind.
# Usage: scripts/phase10/run_comparison.sh DEVICE_ID   (the Claude in Chrome browser on this Mac, chosen by the user)
set -e
device="${1:?usage: run_comparison.sh DEVICE_ID}"
cd "$(dirname "$0")/../.."
tasks=(nav-python-macos nav-wikipedia-turing-machine nav-hackernews-past nav-github-cpython-issues nav-pypi-requests-history
  search-wikipedia-lovelace search-pypi-httpx search-wiktionary-serendipity search-duckduckgo-rust search-python-docs-taskgroup
  forms-flights-example forms-flights-geneva-berlin forms-bmi-metric forms-date-duration forms-httpbin-pizza
  nav-sqlite-download nav-xkcd-archive nav-rust-std-vec nav-huggingface-whisper-files nav-apod-archive
  search-mdn-flexbox search-pubmed-crispr search-sep-free-will search-crates-tokio search-gutenberg-moby-dick
  forms-arxiv-diffusion-dates forms-nominatim-downing-street forms-clinicaltrials-asthma forms-datatracker-http-fielding forms-wikivoyage-compare)
for task in $tasks; do
  for arm in chrome executor; do
    # Resumable: a (task, arm) already recorded without a harness error is never run again.
    if [[ -f artifacts/phase10/comparison.jsonl ]] && python3 -c "import json, sys; sys.exit(0 if any(r['task'] == '$task' and r['arm'] == '$arm' and not r.get('harness_error') for r in map(json.loads, open('artifacts/phase10/comparison.jsonl'))) else 1)"; then
      echo "$(date +%H:%M:%S) $task $arm already recorded"; continue
    fi
    echo "$(date +%H:%M:%S) $task $arm"
    uv run python scripts/phase10/run_arm.py "$task" "$arm" --device "$device"
    # A pilot of one per run of this script: stop if its first Chrome session found no tab (wrong browser selected).
    if [[ $arm == chrome && -z $piloted ]]; then
      piloted=1
      if tail -1 artifacts/phase10/comparison.jsonl | grep -q harness_error; then
        echo "The first Claude in Chrome session found no tab on the task's site; check the device ID." >&2
        exit 1
      fi
    fi
  done
done
uv run python scripts/phase10/compare.py
