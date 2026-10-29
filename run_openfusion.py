#!/usr/bin/env python3
"""Run OpenFusion from the checkout without installing it:  python run_openfusion.py <command> ...

Works the same on Windows, macOS and Linux. Needs only Python 3.9+ (PyYAML only to read an edited YAML config).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "core" / "router"))
from openfusion.cli import main  # noqa: E402

raise SystemExit(main())
