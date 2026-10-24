#!/usr/bin/env bash
# Lock every rendered apko config. Unreleased transitive packages are pinned to
# their newest release and re-locked; a line that can't be made release-only is
# restored to its committed state and reported. Prints one blocked line per row.
set -uo pipefail
blocked=()
for cfg in locks/*/*/*.apko.yaml; do
  lock="${cfg%.apko.yaml}.lock.json"
  dir=$(dirname "$cfg")
  # A line is all-or-nothing: once one variant is blocked, leave the rest restored.
  [[ " ${blocked[*]-} " == *" $dir "* ]] && continue
  ok=0
  for attempt in 1 2 3 4 5; do
    if ! apko lock "$cfg" --output "$lock" > "$RUNNER_TEMP/lock.log" 2>&1; then
      echo "::warning::apko lock failed for $cfg"; tail -5 "$RUNNER_TEMP/lock.log"; break
    fi
    uv run dl pin-released --config "$cfg" --lock "$lock"
    rc=$?
    if [[ $rc -eq 0 ]]; then
      uv run dl lock-check "$lock" && ok=1
      break
    elif [[ $rc -ne 3 ]]; then
      break
    fi
  done
  if [[ $ok -ne 1 ]]; then
    blocked+=("$dir")
    if git ls-files --error-unmatch "$dir" >/dev/null 2>&1; then
      git checkout -- "$dir"
    else
      rm -r "$dir"
    fi
  fi
done
printf '%s\n' "${blocked[@]+"${blocked[@]}"}" | sort -u > "$RUNNER_TEMP/blocked.txt"
