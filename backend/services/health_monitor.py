"""Runtime health monitoring: event-loop stalls, runaway clients, slow endpoints.

Built after a browser tab stuck in a request loop (~12 req/s on
/api/spansh/enrich/batch) blocked the event loop and made every request take
~1s.  Three detectors:

  * Loop stall   — a task sleeps LOOP_TICK_S and measures how late it wakes.
                   Lateness beyond LOOP_STALL_S means something blocked the
                   event loop; the alert names the requests in flight.
  * Client flood — per (client IP, endpoint) request count over a sliding
                   minute.  Past CLIENT_RATE_LIMIT the client gets HTTP 429
                   on that endpoint and an alert is raised.
  * Slow endpoint— rolling p95 latency per endpoint; alert when it exceeds
                   SLOW_P95_S.

Alerts are logged and, when HEALTH_ALERT_ES_URL is set, indexed into the
Elasticsearch index HEALTH_ALERT_INDEX (e.g. one an anomaly board reads; the
document carries tier / urgency_label / fingerprint fields).  Each alert key
is sent at most once per ALERT_COOLDOWN_S.  GET /api/telemetry/health returns
the current state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("health_monitor")

LOOP_TICK_S        = float(os.getenv("HEALTH_LOOP_TICK_S", "0.5"))
LOOP_STALL_S       = float(os.getenv("HEALTH_LOOP_STALL_S", "0.25"))
CLIENT_WINDOW_S    = 60.0
CLIENT_RATE_LIMIT  = int(os.getenv("HEALTH_CLIENT_RATE_LIMIT", "60"))   # per endpoint per minute
SLOW_P95_S         = float(os.getenv("HEALTH_SLOW_P95_S", "5.0"))
SLOW_MIN_SAMPLES   = 20
LATENCY_SAMPLES    = 200
ALERT_COOLDOWN_S   = float(os.getenv("HEALTH_ALERT_COOLDOWN_S", "900"))
ALERT_ES_URL       = os.getenv("HEALTH_ALERT_ES_URL", "").rstrip("/")
ALERT_INDEX        = os.getenv("HEALTH_ALERT_INDEX", "ppa-health-alerts")
SOURCE_ID          = os.getenv("HEALTH_SOURCE_ID", "ppa-backend")

# Paths never rate-limited or counted (probes)
EXEMPT_PATHS = {"/health"}


def client_ip(request: Request) -> str:
    """The real browser IP: Cloudflare's header, then the first
    X-Forwarded-For hop (nginx appends to it), then the socket peer."""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


def endpoint_key(request: Request) -> str:
    """Route template (/api/powers/{name}/systems) so one endpoint is one key
    regardless of path parameters; falls back to the raw path."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


class HealthMonitor:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.in_flight: dict[int, tuple[str, str, float]] = {}   # id -> (endpoint, client, start)
        self.client_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self.latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=LATENCY_SAMPLES))
        self.max_loop_lag = 0.0
        self.last_loop_lag = 0.0
        self.stalls = 0
        self.throttled = 0
        self.recent_alerts: deque[dict] = deque(maxlen=50)
        self._last_sent: dict[str, float] = {}
        self._next_id = 0

    # ── requests ─────────────────────────────────────────────────────────────

    def begin(self, endpoint: str, client: str) -> int:
        self._next_id += 1
        self.in_flight[self._next_id] = (endpoint, client, time.time())
        return self._next_id

    def end(self, req_id: int, duration: float) -> None:
        endpoint, _, _ = self.in_flight.pop(req_id, ("?", "?", 0.0))
        samples = self.latencies[endpoint]
        samples.append(duration)
        if len(samples) >= SLOW_MIN_SAMPLES:
            p95 = self.p95(endpoint)
            if p95 > SLOW_P95_S:
                self.alert(
                    f"slow_endpoint:{endpoint}", "investigate", "moderate risk",
                    f"{endpoint} p95 latency {p95:.1f}s over the last {len(samples)} requests",
                    {"endpoint": endpoint, "p95_s": round(p95, 2), "samples": len(samples)},
                )

    def over_limit(self, client: str, endpoint: str) -> bool:
        """Record a hit; True when this client is over the per-minute limit
        for this endpoint."""
        now = time.time()
        hits = self.client_hits[(client, endpoint)]
        hits.append(now)
        while hits and hits[0] < now - CLIENT_WINDOW_S:
            hits.popleft()
        if len(hits) > CLIENT_RATE_LIMIT:
            self.throttled += 1
            self.alert(
                f"client_flood:{client}:{endpoint}", "immediate", "high risk",
                f"Client {client} sent {len(hits)} requests/min to {endpoint} "
                f"(limit {CLIENT_RATE_LIMIT}); throttling with HTTP 429",
                {"client_ip": client, "endpoint": endpoint, "requests_per_min": len(hits),
                 "limit": CLIENT_RATE_LIMIT},
                src_ip=client,
            )
            return True
        return False

    def p95(self, endpoint: str) -> float:
        samples = sorted(self.latencies[endpoint])
        return samples[int(0.95 * (len(samples) - 1))] if samples else 0.0

    # ── event loop ───────────────────────────────────────────────────────────

    async def watch_loop(self) -> None:
        while True:
            start = time.perf_counter()
            await asyncio.sleep(LOOP_TICK_S)
            lag = time.perf_counter() - start - LOOP_TICK_S
            self.last_loop_lag = lag
            self.max_loop_lag = max(self.max_loop_lag, lag)
            if lag > LOOP_STALL_S:
                self.stalls += 1
                now = time.time()
                busy: dict[str, int] = defaultdict(int)
                for endpoint, _, started in self.in_flight.values():
                    busy[endpoint] += 1
                top = sorted(busy.items(), key=lambda kv: -kv[1])[:5]
                oldest = max((now - s for _, _, s in self.in_flight.values()), default=0.0)
                self.alert(
                    "loop_stall", "immediate", "high risk",
                    f"Event loop stalled {lag:.2f}s; in flight: "
                    + (", ".join(f"{e} x{n}" for e, n in top) or "nothing"),
                    {"lag_s": round(lag, 3), "in_flight": dict(top),
                     "in_flight_total": len(self.in_flight), "oldest_request_s": round(oldest, 1)},
                )

    # ── alerts ───────────────────────────────────────────────────────────────

    def alert(self, key: str, tier: str, urgency_label: str, message: str,
              details: dict, src_ip: Optional[str] = None) -> None:
        now = time.time()
        if now - self._last_sent.get(key, 0.0) < ALERT_COOLDOWN_S:
            return
        self._last_sent[key] = now
        logger.warning("HEALTH ALERT [%s] %s", key, message)
        doc = {
            "source_type": "app_health",
            "source_id": SOURCE_ID,
            "ts": now,
            "src_ip": src_ip,
            "hostname": socket.gethostname(),
            "event_type": "app_health",
            "fingerprint": f"ppa:{key}",
            "urgency_label": urgency_label,
            "urgency_score": {"high risk": 3.0, "moderate risk": 2.0}.get(urgency_label, 1.0),
            "tier": tier,
            "message": message,
            "raw": details,
            "scored_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        }
        self.recent_alerts.appendleft(doc)
        if ALERT_ES_URL:
            # Off the event loop: a slow or down Elasticsearch must not add
            # to the very stall being reported
            try:
                asyncio.get_running_loop().run_in_executor(None, _post_alert, doc)
            except RuntimeError:
                _post_alert(doc)

    # ── state ────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        now = time.time()
        busiest = sorted(
            ((c, e, sum(1 for t in hits if t >= now - CLIENT_WINDOW_S))
             for (c, e), hits in self.client_hits.items()),
            key=lambda x: -x[2],
        )[:10]
        slow = sorted(
            ({"endpoint": e, "p95_s": round(self.p95(e), 3), "samples": len(s)}
             for e, s in self.latencies.items() if s),
            key=lambda x: -x["p95_s"],
        )[:10]
        return {
            "uptime_s": round(now - self.started_at),
            "loop_lag_s": round(self.last_loop_lag, 4),
            "max_loop_lag_s": round(self.max_loop_lag, 3),
            "loop_stalls": self.stalls,
            "throttled_requests": self.throttled,
            "in_flight": len(self.in_flight),
            "busiest_clients": [
                {"client_ip": c, "endpoint": e, "requests_per_min": n} for c, e, n in busiest if n
            ],
            "slowest_endpoints": slow,
            "recent_alerts": list(self.recent_alerts)[:20],
            "limits": {
                "loop_stall_s": LOOP_STALL_S, "client_rate_per_min": CLIENT_RATE_LIMIT,
                "slow_p95_s": SLOW_P95_S, "alerts_to": ALERT_INDEX if ALERT_ES_URL else None,
            },
        }


def _post_alert(doc: dict) -> None:
    try:
        req = urllib.request.Request(
            f"{ALERT_ES_URL}/{ALERT_INDEX}/_doc",
            data=json.dumps(doc).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:
        logger.warning("Could not send health alert to %s: %s", ALERT_ES_URL, exc)


monitor = HealthMonitor()


class HealthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in EXEMPT_PATHS:
            return await call_next(request)
        client = client_ip(request)
        # The route isn't resolved until the router runs, so the rate limit
        # and the in-flight list use the raw path; latency is recorded under
        # the route template once it is known.
        if monitor.over_limit(client, path):
            return JSONResponse(
                {"detail": "Too many requests — slow down"},
                status_code=429, headers={"Retry-After": "30"},
            )
        req_id = monitor.begin(path, client)
        start = time.perf_counter()
        try:
            return await call_next(request)
        finally:
            _, c, s = monitor.in_flight.get(req_id, (path, client, start))
            monitor.in_flight[req_id] = (endpoint_key(request), c, s)
            monitor.end(req_id, time.perf_counter() - start)
