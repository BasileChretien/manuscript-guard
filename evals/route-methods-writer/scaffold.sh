#!/usr/bin/env bash
# The worked example, as the project the prompt speaks of: tools/run_skill_evals.py puts a
# copy of it beside the cases, as _project, when it stages the suite.
set -eu
project="$(cd "$(dirname "$0")/.." && pwd)/_project"
if [ ! -d "$project" ]; then
  echo "no $project: run the suite with tools/run_skill_evals.py" >&2
  exit 1
fi
cp -R "$project/." .
