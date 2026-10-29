#!/usr/bin/env python3
"""OpenFusion router bundled with this skill (generated; edit core/openfusion.yaml instead).

    python route.py --json "fix the flaky checkout test"
    python route.py judge < reply.txt
Needs only Python 3.9+ (no packages). Works the same on Windows, macOS and Linux.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from openfusion.cli import main  # noqa: E402

COMMANDS = {"route", "escalate", "judge", "tiers", "resolve", "harnesses", "list-harnesses", "-h", "--help", "--version"}
args = sys.argv[1:]
if not args or args[0] not in COMMANDS:
    args = ["route", *args]
raise SystemExit(main(["--config", str(HERE / "openfusion.json"), *args]))
