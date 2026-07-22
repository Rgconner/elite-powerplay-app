"""
Backwards-compatible entrypoint.

The old VisInsp project had a ``src/visinsp/main.py`` with a ``run()``
function. We re-export it here so any old scripts keep working, and
delegate to the new :mod:`visinsp.services.cli` for the modern interface.

Prefer ``python -m visinsp <subcommand>`` for new code.
"""

from __future__ import annotations

import sys
from typing import Optional

from . import __version__
from .config import load_config
from .logging_setup import configure_logging
from .paths import resolve_paths


def hello_visinsp(name: Optional[str] = None) -> str:
    """Greeting helper kept for the original API."""
    if name:
        return f"Hello from Visual Inspector, {name}!"
    return "Hello from Visual Inspector!"


def run(config=None) -> None:
    """Start the full daemon (GPIO + web) — equivalent to ``python -m visinsp run``."""
    from .services.cli import cmd_run
    import argparse
    args = argparse.Namespace()
    return cmd_run(args)


def main() -> int:
    try:
        run()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Error: {e}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
