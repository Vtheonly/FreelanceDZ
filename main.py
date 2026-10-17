"""Entry point: `python main.py` starts the API server + dashboard."""

import sys

from cli import cli


def main() -> None:
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    cli()


if __name__ == "__main__":
    main()
