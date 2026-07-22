"""Runnable service entrypoints.

The three services in this package are:

* :func:`daemon.run`   — the background daemon: GPIO watch loop, retention,
                         and (optionally) starting the web server too.
* :func:`web_server.run` — just the Flask + SocketIO server.
* :func:`mock_hardware.tick` — helper for tests / scripts to drive the mock
  GPIO from outside the daemon thread.

The :mod:`cli` module glues them together with subcommands and is the
single user-facing entrypoint (``python -m visinsp``).
"""

from . import cli, daemon, mock_hardware, web_server

__all__ = ["cli", "daemon", "mock_hardware", "web_server"]
