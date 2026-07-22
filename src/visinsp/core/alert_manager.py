"""Alert manager.

Creates :class:`AlertRecord` entries for failed inspections, dispatches
the configured actions (GPIO, sound, visual, notification), and applies
operator-verdict feedback to the job's threshold.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from ..models import (
    Action,
    AlertRecord,
    AlertVerdict,
    InspectionResult,
    Job,
    NotificationAction,
    VisualAction,
)
from ..actions import get_action_registry
from .event_bus import get_event_bus
from .state_store import StateStore
from .threshold import apply_verdict

log = logging.getLogger(__name__)


class AlertManager:
    """Glues state, actions, and event publishing for alerts."""

    def __init__(self, state: StateStore):
        self.state = state
        self.bus = get_event_bus()

    # ---- raising alerts ----

    def raise_alert(
        self,
        inspection: InspectionResult,
        job: Job,
    ) -> Optional[AlertRecord]:
        """Create a new pending alert for a failed inspection and fire actions."""
        if inspection.passed:
            return None
        alert = AlertRecord(
            id=f"alert_{uuid.uuid4().hex[:10]}",
            inspection_id=inspection.id,
            job_id=job.id,
            raised_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            verdict=AlertVerdict.PENDING,
            image_path=inspection.image_path,
            score=inspection.score_overall,
            threshold=inspection.threshold,
        )
        self.state.create_alert(alert)
        log.info("alert raised: id=%s job=%s score=%.4f threshold=%.4f",
                 alert.id, job.id, alert.score, alert.threshold)

        # Publish + fire actions (fail set)
        self.bus.publish("alert_new", alert.to_dict())
        self._fire_actions(job.actions_on_fail, {
            "alert_id": alert.id,
            "inspection_id": inspection.id,
            "job_id": job.id,
            "score": inspection.score_overall,
            "threshold": inspection.threshold,
            "kind": "fail",
        })
        return alert

    def record_pass(
        self,
        inspection: InspectionResult,
        job: Job,
    ) -> None:
        """No alert, but still fire any 'on pass' actions."""
        self._fire_actions(job.actions_on_pass, {
            "inspection_id": inspection.id,
            "job_id": job.id,
            "score": inspection.score_overall,
            "threshold": inspection.threshold,
            "kind": "pass",
        })

    # ---- dismissing alerts ----

    def dismiss_alert(
        self,
        alert_id: str,
        verdict: AlertVerdict,
        notes: str = "",
        actor: str = "operator",
    ) -> Optional[Dict[str, Any]]:
        """Dismiss an alert with the given verdict.

        On a ``false_positive`` or ``false_negative`` verdict, the
        job's threshold is auto-adjusted and a history row is recorded.
        Returns a small dict describing the outcome, or ``None`` if the
        alert didn't exist.
        """
        alert = self.state.get_alert(alert_id)
        if not alert:
            return None
        if alert.verdict.is_dismissed():
            return {"alert": alert.to_dict(), "changed": False, "reason": "already_dismissed"}

        dismissed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.state.dismiss_alert(alert_id, verdict, dismissed_at, notes=notes)
        # Re-read to get the dismissed state
        alert = self.state.get_alert(alert_id)  # type: ignore[assignment]

        changed = False
        new_threshold = None
        old_threshold = None
        job = self.state.get_job(alert.job_id)
        if job and verdict in (AlertVerdict.FALSE_POSITIVE, AlertVerdict.FALSE_NEGATIVE):
            settings = self.state.get_settings()
            new_threshold, changed = apply_verdict(
                current_threshold=job.threshold,
                step=job.threshold_step or settings.default_threshold_step,
                verdict=verdict,
                min_value=settings.min_threshold,
                max_value=settings.max_threshold,
            )
            if changed:
                old_threshold = job.threshold
                job.threshold = new_threshold
                job.updated_at = dismissed_at
                self.state.upsert_job(job)
                self.state.record_threshold_change(
                    job_id=job.id,
                    old_value=old_threshold,
                    new_value=new_threshold,
                    reason=verdict.value,
                    alert_id=alert.id,
                    created_at=dismissed_at,
                )
                log.info("threshold auto-adjust: job=%s %.4f → %.4f (%s)",
                         job.id, old_threshold, new_threshold, verdict.value)
                self.bus.publish("threshold_changed", {
                    "job_id": job.id,
                    "old_value": old_threshold,
                    "new_value": new_threshold,
                    "verdict": verdict.value,
                    "actor": actor,
                })

        self.bus.publish("alert_resolved", {
            "alert": alert.to_dict() if alert else None,
            "changed": changed,
            "new_threshold": new_threshold,
            "old_threshold": old_threshold,
            "actor": actor,
        })
        return {
            "alert": alert.to_dict() if alert else None,
            "changed": changed,
            "new_threshold": new_threshold,
            "old_threshold": old_threshold,
        }

    # ---- helpers ----

    def _fire_actions(self, actions: List[Action], context: Dict[str, Any]) -> None:
        if not actions:
            return
        registry = get_action_registry()
        for action in actions:
            try:
                handler = registry.get(action.type)
            except KeyError:
                log.warning("no handler registered for action type %r", action.type)
                continue
            try:
                handler(action, context)
            except Exception:  # noqa: BLE001
                log.exception("action handler %r failed", action.type)


__all__ = ["AlertManager"]
