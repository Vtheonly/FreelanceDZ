"""Main entry point — runs the default discovery pipeline.

This is kept so the original ``python main.py`` invocation still works.
For interactive use, prefer ``python cli.py`` (richer command set).

The default behaviour is a single discover → analyze → score → resolve
run for the "Logistics" industry in Algiers with a limit of 5 leads —
small enough to run in a few seconds on a fresh database, large enough
to exercise every layer of the pipeline.
"""

from __future__ import annotations

import asyncio
import logging

from cli import cli


_logger = logging.getLogger("main")


def main() -> None:
    """Run the default pipeline when invoked with no arguments."""
    import sys
    if len(sys.argv) == 1:
        # Default to a small discover → analyze → score run.
        sys.argv.extend([
            "discover",
            "--query", "Logistics",
            "--wilaya", "Algiers",
            "--limit", "5",
        ])
    cli()


if __name__ == "__main__":
    main()
