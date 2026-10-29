#!/usr/bin/env bash
# OpenFusion installer for macOS and Linux (same behavior as install.ps1 on Windows).
# A thin wrapper around `openfusion install` that runs straight from this checkout.
# Prefer the package when you can:  uvx openfusion install <harness> <repo>
#
#   ./install.sh <harness> [path-to-your-repo] [--no-instructions] [--codex-profiles] [--available MODELS]
#   harness: claude-code | codex | cursor | github-copilot | gemini-cli | antigravity | opencode | generic
#
# Needs only Python 3.9+ (no packages). Uses ./.venv if one exists (e.g. with PyYAML, to read an edited
# core/openfusion.yaml). Nothing is uploaded; files are only written into the repo you name.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 || "$1" == -* ]]; then
  echo "usage: ./install.sh <harness> [path-to-your-repo] [--no-instructions] [--codex-profiles] [--available MODELS]" >&2
  echo "harnesses: claude-code codex cursor github-copilot gemini-cli antigravity opencode generic" >&2
  exit 2
fi

py="${OPENFUSION_PYTHON:-}"
if [[ -z "$py" && -x "$here/.venv/bin/python" ]]; then py="$here/.venv/bin/python"; fi
if [[ -z "$py" ]]; then
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
      py="$cand"; break
    fi
  done
fi
[[ -n "$py" ]] || { echo "error: Python 3.9+ not found (install it or set OPENFUSION_PYTHON)" >&2; exit 1; }

exec "$py" "$here/run_openfusion.py" install "$@"
