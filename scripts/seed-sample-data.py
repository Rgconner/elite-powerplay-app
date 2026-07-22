"""
Thin shim for the sample-data seeder.

The real implementation lives in :mod:`visinsp.services.seed`. This
file exists so the old command ``python scripts/seed-sample-data.py``
still works for anyone who learned it from an earlier version.

New code should use ``python -m visinsp.services.cli seed [--count N]``
or invoke the :func:`visinsp.services.seed.seed` function directly.
"""

from __future__ import annotations

import sys

from visinsp.config import load_config
from visinsp.paths import resolve_paths
from visinsp.services.seed import seed as _seed


def main() -> int:
    count = 5
    # First positional arg (if any) is the count, matching the old CLI.
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
        except ValueError:
            print(f"Ignoring non-integer count argument: {sys.argv[1]!r}", file=sys.stderr)
    cfg = load_config()
    paths = resolve_paths(cfg)
    _seed(paths, count=count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
