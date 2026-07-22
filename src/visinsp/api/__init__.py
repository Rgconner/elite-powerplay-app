"""Flask + SocketIO HTTP/WS API for Visual Inspector.

The :func:`create_app` factory builds the Flask app, registers every
blueprint, wires the SocketIO server, and returns both. The
:mod:`services.web_server` entrypoint calls this and runs the server.

Routes are split into a few small blueprints:

* ``/api/pins``        — pin state, manual toggle (mock)
* ``/api/cameras``     — list cameras, capture
* ``/api/references``  — CRUD + bbox editing
* ``/api/triggers``    — pin → job triggers
* ``/api/jobs``        — inspection jobs
* ``/api/inspections`` — recent inspection results + run-now
* ``/api/alerts``      — alert history + dismiss (VP / FP / FN)
* ``/api/settings``    — global tunables
"""

from .app import AppContext, create_app, create_socketio

__all__ = ["create_app", "create_socketio", "AppContext"]
