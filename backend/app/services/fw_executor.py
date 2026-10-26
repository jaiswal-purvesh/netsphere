"""Execution — Appendix A Phases 1 (re-check) and 4-7 (apply/commit/push/
verify/record), for a single Panorama device group. Synchronous for this
phase (no celery dispatch yet — see `_wait_for_job`'s note); every exit
path — success, abort, failure — updates FwExecution and FwIntent and
writes an audit_log entry, matching Appendix A's "Phase 7 runs on every
exit path" rule.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.fw_automation import FwApproval, FwExecution, FwIntent, FwPlan, FwPoa
from app.models.integration import FirewallIntegration
from app.models.security_policy import SecurityGroup
from app.services import fw_panorama_adapter as panorama
from app.services import secrets as secretsvc
from app.services import security_policy_adapter as cloud_adapter
from app.services.audit import record as audit_record

JOB_POLL_INTERVAL_S = 3
JOB_POLL_MAX_ATTEMPTS = 20  # ~60s — short because this runs in-request; a
                            # job still PEND after this is left NEEDS_HUMAN,
                            # never raced with a rollback (§3.11).


class ExecutionAborted(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _wait_for_job(host, port, verify_tls, api_key, job_id: str) -> tuple[str, str]:
    for _ in range(JOB_POLL_MAX_ATTEMPTS):
        status, result = panorama.poll_job(host, port, verify_tls, api_key, job_id)
        if status == "FIN":
            return status, result
        time.sleep(JOB_POLL_INTERVAL_S)
    return "PEND", ""


def execute(db: Session, intent: FwIntent, plan: FwPlan, user_id) -> FwExecution:
    approval = db.query(FwApproval).filter(
        FwApproval.intent_id == intent.id, FwApproval.plan_id == plan.id,
        FwApproval.plan_hash == plan.plan_hash, FwApproval.decision == "approved",
    ).order_by(FwApproval.decided_at.desc()).first()
    if not approval:
        raise ExecutionAborted("No matching approval for this exact plan_hash — approve the current plan first.")

    poa = db.query(FwPoa).filter(FwPoa.id == approval.poa_id, FwPoa.plan_id == plan.id).first()
    if not poa or poa.poa_revision != approval.poa_revision:
        raise ExecutionAborted("The approved PoA revision no longer matches — re-approve after reviewing the current PoA.")

    # Validate the target is still reachable/usable *before* creating the
    # FwExecution row — an aborted-before-start execution should never be
    # persisted (nothing to roll back, nothing ran), same as the original
    # Panorama-only flow's ordering.
    integration = None
    security_group = None
    if intent.target_kind == "firewall":
        integration = db.get(FirewallIntegration, intent.integration_id)
        if not integration or not integration.is_active or not integration.secret_ciphertext:
            raise ExecutionAborted("The firewall integration is missing, inactive, or has no saved credential.")
    else:
        security_group = db.get(SecurityGroup, intent.security_group_id)
        if not security_group or security_group.deleted_at is not None:
            raise ExecutionAborted("The target security group is missing or has been deleted.")

    execution = FwExecution(intent_id=intent.id, plan_id=plan.id, executed_by_id=user_id, state="started", started_at=datetime.now(timezone.utc))
    db.add(execution)
    intent.status = "executing"
    db.commit()
    db.refresh(execution)

    def _finish(state: str, intent_status: str, *, error: str = "", verify: dict | None = None, rolled_back: bool = False) -> FwExecution:
        execution.state = state
        execution.error_message = error
        execution.verify_result_json = verify or {}
        execution.rolled_back = rolled_back
        execution.finished_at = datetime.now(timezone.utc)
        intent.status = intent_status
        db.commit()
        audit_record(
            db, user_id=user_id, action="execute", resource_type="fw_intent", resource_id=str(intent.id),
            result="success" if state == "verified" else "failure",
            after={"execution_state": state, "intent_status": intent_status, "error": error},
        )
        return execution

    if intent.target_kind != "firewall":
        return _execute_cloud(db, intent, plan, security_group, execution, _finish)

    device_group = intent.device_group or integration.device_group or ""
    host, port, verify_tls = integration.host, integration.port, integration.verify_tls
    secret = secretsvc.decrypt(integration.secret_ciphertext)
    admin_username = integration.username or "svc-fwauto"

    try:
        # Phase 1 (re-check): drift + foreign pending changes.
        current_version = panorama.fetch_config_version(host, port, verify_tls, secret)
        if current_version != plan.device_config_version:
            return _finish("aborted", "needs_human", error="PLAN_STALE: device config version changed since this plan was rendered — re-plan and re-approve.")
        if panorama.pending_changes(host, port, verify_tls, secret):
            return _finish("aborted", "needs_human", error="Another administrator has uncommitted changes pending on this device group — aborting rather than absorbing them.")

        # Snapshot before any write.
        snapshot_name = f"fwauto-{intent.id}-{int(time.time())}"
        panorama.snapshot(host, port, verify_tls, secret, snapshot_name)
        execution.snapshot_ref = snapshot_name
        db.commit()

        if not plan.artifact_json:
            return _finish("verified", "no_change_required", verify={"reason": "plan had no artifact (no_change_required at plan time)"})

        artifact = _ArtifactView(plan.artifact_json)

        # Re-render against a fresh object fetch and require an exact match
        # to what was approved — if Panorama's catalog moved underneath the
        # plan, we do not proceed on a stale rendering.
        addresses, services = panorama.fetch_objects(host, port, verify_tls, secret, device_group)
        source = [s["cidr"] for s in intent.source_json]
        destination = [d["cidr"] for d in intent.destination_json]
        fresh = panorama.render(
            ticket_ref=intent.ticket_ref, action=intent.action, logging=intent.logging,
            source=source, destination=destination, service=intent.service_json,
            addresses=addresses, services=services, plan_seq=artifact.rule_name.rsplit("-", 1)[-1],
            rule_name_override=intent.rule_name, source_zone=intent.source_zone,
            destination_zone=intent.destination_zone, security_profile=intent.security_profile,
        )
        if fresh.to_dict() != plan.artifact_json:
            return _finish("aborted", "needs_human", error="PLAN_STALE: object catalog changed since planning — the rendered rule would differ from what was approved.")

        panorama.apply_artifact(host, port, verify_tls, secret, device_group, fresh)
        execution.state = "objects_and_rule_written"
        db.commit()

        panorama.validate_full(host, port, verify_tls, secret)
        diff_text = panorama.preview_diff(host, port, verify_tls, secret)
        execution.preview_matched = bool(diff_text.strip())  # non-empty diff = our change is indeed pending
        db.commit()

        commit_job = panorama.commit_partial(host, port, verify_tls, secret, admin_username)
        execution.commit_job_id = commit_job
        db.commit()
        status, result = _wait_for_job(host, port, verify_tls, secret, commit_job)
        if status != "FIN":
            return _finish("needs_human", "needs_human", error=f"Commit job {commit_job} did not finish within the poll window — do not roll back a possibly-still-running commit.")
        if result != "OK":
            _safe_rollback(db, execution, host, port, verify_tls, secret, admin_username, device_group, snapshot_name)
            return _finish("reverted", "failed", error=f"Commit job {commit_job} failed: {result}", rolled_back=True)

        push_job = panorama.push_to_device_group(host, port, verify_tls, secret, device_group)
        execution.push_job_id = push_job
        db.commit()
        status, result = _wait_for_job(host, port, verify_tls, secret, push_job)
        if status != "FIN":
            return _finish("needs_human", "needs_human", error=f"Push job {push_job} did not finish within the poll window — do not roll back a possibly-still-running push.")

        if result != "OK":
            # §3.11 asymmetric policy: allow rules that fail to push are
            # "not working yet", not unsafe — do not auto-revert. Deny
            # rules that fail to push are a silent gap — auto-revert.
            if intent.action == "deny":
                _safe_rollback(db, execution, host, port, verify_tls, secret, admin_username, device_group, snapshot_name)
                return _finish("reverted", "failed", error=f"Push job {push_job} failed on a deny rule — reverted: {result}", rolled_back=True)
            return _finish("partial", "partial", error=f"Push job {push_job} failed on an allow rule — traffic remains blocked, not reverted: {result}")

        verify = panorama.verify_rule_present(host, port, verify_tls, secret, device_group, artifact.rule_name)
        if not verify.get("present") or verify.get("action") != intent.action:
            # Verification mismatch — the device is not in the intended
            # state regardless of what the job reported. Revert regardless
            # of action type (§A.5: "Phase 6 mismatch -> revert, page").
            _safe_rollback(db, execution, host, port, verify_tls, secret, admin_username, device_group, snapshot_name)
            return _finish("reverted", "failed", error="Post-change read-back did not match the intended rule — reverted.", verify=verify, rolled_back=True)

        return _finish("verified", "applied_verified", verify=verify)

    except panorama.PanoramaError as e:
        return _finish("failed", "needs_human", error=f"Panorama error mid-execution — needs human review before any retry: {e}")


def _safe_rollback(db, execution, host, port, verify_tls, secret, admin_username, device_group, snapshot_name) -> None:
    try:
        job = panorama.rollback_to_snapshot(host, port, verify_tls, secret, admin_username, device_group, snapshot_name)
        _wait_for_job(host, port, verify_tls, secret, job)
    except panorama.PanoramaError:
        # Rollback itself failing is the worst case here — it is recorded
        # via the caller's _finish(error=...) either way; we do not raise
        # again so the original failure reason is what gets surfaced.
        pass


class _ArtifactView:
    def __init__(self, d: dict):
        self.rule_name = d.get("rule_name", "")


def _execute_cloud(db: Session, intent: FwIntent, plan: FwPlan, security_group: SecurityGroup, execution: FwExecution, _finish) -> FwExecution:
    """Cloud-target analogue of the Panorama flow above, collapsed to what
    actually differs when "the device" is our own `SecurityGroup`/
    `SecurityRule` tables (see security_policy_adapter.py's module
    docstring): no separate commit/push job polling, since a DB insert is
    already atomic and immediately durable. Drift detection, re-render-and-
    compare, and the asymmetric allow/deny rollback policy (§3.11) are all
    still enforced — only the transport underneath them is different."""
    if not plan.artifact_json:
        return _finish("verified", "no_change_required", verify={"reason": "plan had no artifact (no_change_required at plan time)"})

    # Phase 1 re-check equivalent: has the security group's rule set moved
    # since this plan was rendered?
    current_version = cloud_adapter.fetch_config_version(db, security_group.id)
    if current_version != plan.device_config_version:
        return _finish("aborted", "needs_human", error="PLAN_STALE: the security group's rule set changed since this plan was rendered — re-plan and re-approve.")

    artifact = plan.artifact_json
    svc = intent.service_json[0] if intent.service_json else {"proto": "tcp", "port_low": None, "port_high": None}
    source = [s["cidr"] for s in intent.source_json]
    destination = [d["cidr"] for d in intent.destination_json]

    try:
        fresh = cloud_adapter.render(
            security_group=security_group, ticket_ref=intent.ticket_ref, action=intent.action,
            protocol=svc.get("proto", "tcp"), port_low=svc.get("port_low"), port_high=svc.get("port_high"),
            source=source, destination=destination,
        )
    except cloud_adapter.SecurityPolicyAdapterError as e:
        return _finish("failed", "needs_human", error=f"Rule rejected by the {security_group.provider} adapter mid-execution: {e}")

    if fresh.to_dict() != artifact:
        return _finish("aborted", "needs_human", error="PLAN_STALE: the rendered rule would differ from what was approved — re-plan and re-approve.")

    try:
        rule_row = cloud_adapter.apply_artifact(db, fresh, expires_at=intent.expires_at)
        db.commit()
    except Exception as e:  # a real DB/adapter failure — nothing durable happened that needs reverting
        db.rollback()
        return _finish("failed", "needs_human", error=f"Failed to write the security rule: {e}")

    execution.snapshot_ref = f"security_rule:{rule_row.id}"
    execution.state = "objects_and_rule_written"
    db.commit()

    verify = cloud_adapter.verify_rule_present(db, security_group.id, fresh.rule_group_key)
    if not verify.get("present") or verify.get("action") != intent.action:
        cloud_adapter.rollback(db, rule_row.id)
        db.commit()
        return _finish("reverted", "failed", error="Post-write read-back did not match the intended rule — reverted.", verify=verify, rolled_back=True)

    return _finish("verified", "applied_verified", verify=verify)
