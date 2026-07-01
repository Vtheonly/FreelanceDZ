"""Backward-compatible entry point — runs the full pipeline once.

This is kept so the original `python main.py` invocation from the spec still
works. For interactive use, prefer `python cli.py` (richer command set).
"""

from __future__ import annotations

import sys

from cli import cli


if __name__ == "__main__":
    # If no args provided, default to running the full pipeline.
    if len(sys.argv) == 1:
        sys.argv.extend(["pipeline", "--query", "Logistics", "--limit", "5"])
    cli()
