"""End-to-end orchestration tests: planning, approval interrupts, recovery."""
from __future__ import annotations

from sqlalchemy import select

from langgraph.types import Command

from app.graph import runtime
from app.models import Approval, AuditLog, GeneratedDocument, Workflow
from app.services import audit
from app.services.approvals import decide as decide_approval
from app.services.workflows import build_launch_payload, create_workflow

ONBOARDING_REQUEST = (
    "Onboard Rahul Sharma as a Software Engineer in the Engineering Department."
)


def run_to_completion(db, workflow, approver, *, reject_first: bool = False):
    """Drive the graph, resolving every checkpoint it raises."""
    runtime.run_sync(workflow.id, build_launch_payload(workflow, approver))
    for _ in range(30):
        db.expire_all()
        current = db.get(Workflow, workflow.id)
        pending = list(
            db.scalars(
                select(Approval).where(Approval.workflow_id == workflow.id, Approval.status == "pending")
            )
        )
        if current.status not in ("awaiting_approval",) and not pending:
            return current
        if not pending:
            raise AssertionError(f"Workflow parked in status {current.status} with no pending approval")
        action = "reject" if reject_first else "approve"
        decide_approval(
            db,
            approval_id=pending[0].id,
            user=approver,
            action=action,
            comment="Checked the sandbox impact" if action == "approve" else "Not authorised in this run",
        )
        runtime.run_sync(workflow.id, Command(resume={"source": "test"}))
    raise AssertionError("Workflow did not settle within the expected number of checkpoints")


def test_planner_classifies_onboarding_and_extracts_entities():
    from app.agents.planner import build_plan
    import asyncio

    plan = asyncio.run(build_plan(ONBOARDING_REQUEST))
    assert plan.category == "employee_onboarding"
    assert plan.entities.get("full_name") == "Rahul Sharma"
    assert plan.entities.get("department") == "Engineering"
    assert {task["agent"] for task in plan.tasks} >= {"hr", "document", "it"}
    approval_tasks = [task for task in plan.tasks if task["requires_approval"]]
    assert approval_tasks, "sensitive onboarding actions must require a human checkpoint"


def test_onboarding_pauses_for_approval_then_completes(db, operator, approver):
    workflow = create_workflow(db, user=operator, request_text=ONBOARDING_REQUEST, start=False)
    finished = run_to_completion(db, workflow, approver)

    assert finished.status == "completed", finished.error_message or finished.result_summary
    assert finished.progress == 100.0
    approvals = list(db.scalars(select(Approval).where(Approval.workflow_id == finished.id)))
    assert len(approvals) >= 2
    assert {approval.status for approval in approvals} == {"approved"}
    assert all(approval.decided_by for approval in approvals)

    documents = list(db.scalars(select(GeneratedDocument).where(GeneratedDocument.workflow_id == finished.id)))
    assert {document.doc_type for document in documents} >= {"offer_letter", "onboarding_pack"}

    events = {entry.event_type for entry in db.scalars(select(AuditLog).where(AuditLog.workflow_id == finished.id))}
    assert {"workflow_requested", "workflow_planned", "approval_requested", "approval_granted",
            "tool_invoked", "workflow_completed"} <= events

    report = finished.final_report
    assert report["status"] == "completed"
    assert report["tool_executions"], "the report must list the tool execution history"
    assert report["simulation_notice"]


def test_rejection_stops_dependent_actions(db, operator, approver):
    workflow = create_workflow(db, user=operator, request_text=ONBOARDING_REQUEST, start=False)
    runtime.run_sync(workflow.id, build_launch_payload(workflow, approver))
    pending = list(
        db.scalars(select(Approval).where(Approval.workflow_id == workflow.id, Approval.status == "pending"))
    )
    assert pending
    decide_approval(db, approval_id=pending[0].id, user=approver, action="reject", comment="Policy hold")
    runtime.run_sync(workflow.id, Command(resume={"source": "test"}))
    db.expire_all()
    current = db.get(Workflow, workflow.id)
    assert current.status in ("rejected", "completed_with_exceptions")
    assert current.final_report["rejected_tasks"], "the report must show what was stopped"
    assert current.final_report["skipped_tasks"], "dependent tasks must not run after a rejection"
    assert "skipped because their dependencies were not executed" in current.final_report["headline"]


def test_transient_failure_retries_and_succeeds(db, operator, approver):
    """it.setup_equipment fails on its first attempt by design."""
    workflow = create_workflow(db, user=operator, request_text=ONBOARDING_REQUEST, start=False)
    run_to_completion(db, workflow, approver)
    db.expire_all()
    retries = list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.workflow_id == workflow.id, AuditLog.event_type == "task_retry"
            )
        )
    )
    assert retries, "the equipment task must demonstrate a backoff retry"
    assert "retry 2/3" in retries[0].message


def test_financial_tool_is_never_auto_retried():
    from app.graph.recovery import decide
    from app.tools.definitions import get_tool_definition

    definition = get_tool_definition("finance.create_payment_request")
    decision = decide({}, definition, "transient", "gateway timed out", attempt=1)
    assert decision.retry is False
    assert "not retry-safe" in decision.reason


def test_invoice_and_support_categories_plan_end_to_end(db, operator, approver):
    import asyncio

    from app.agents.planner import build_plan

    invoice = asyncio.run(build_plan("Process invoice INV-88214 from Acme Office Supplies for EUR 1,290.50"))
    assert invoice.category == "invoice_processing"
    assert invoice.entities["invoice_number"] == "INV-88214"
    assert any(task["tool"] == "finance.create_payment_request" for task in invoice.tasks)

    support = asyncio.run(
        build_plan("Customer Beacon Retail Group asks where order ORD-77301 is; ticket TCK-44102 is late.")
    )
    assert support.category == "customer_request"
    assert support.entities.get("order_id") == "ORD-77301"
    assert any(task["agent"] == "support" for task in support.tasks)


def test_registry_blocks_unauthorised_agent_and_invalid_payload(db, operator):
    import pytest

    from app.tools.registry import (
        AuthorizationContext,
        ToolPermissionDenied,
        ToolValidationError,
        registry,
    )

    with pytest.raises(ToolValidationError):
        registry.execute(
            db,
            name="hr.create_employee_record",
            arguments={"department": "Engineering"},
            auth=AuthorizationContext(agent_name="hr", permissions=["*"]),
            workflow_id="WF-TEST",
            task_id="t1",
        )
    with pytest.raises(ToolPermissionDenied):
        registry.execute(
            db,
            name="hr.create_employee_record",
            arguments={"full_name": "Test", "department": "Engineering", "job_title": "Engineer"},
            auth=AuthorizationContext(agent_name="finance", permissions=["*"]),
            workflow_id="WF-TEST",
            task_id="t1",
        )


def test_idempotency_replay_does_not_duplicate_side_effects(db, operator):
    from app.tools.registry import AuthorizationContext, registry

    workflow = create_workflow(db, user=operator, request_text=ONBOARDING_REQUEST, start=False)
    arguments = {"full_name": "Rahul Sharma", "department": "Engineering", "job_title": "Software Engineer"}
    auth = AuthorizationContext(agent_name="hr", permissions=["hr.write"])
    first = registry.execute(
        db, name="hr.create_employee_record", arguments=arguments, auth=auth,
        workflow_id=workflow.id, task_id="t1",
    )
    second = registry.execute(
        db, name="hr.create_employee_record", arguments=arguments, auth=auth,
        workflow_id=workflow.id, task_id="t1",
    )
    assert first.data["employee_code"] == second.data["employee_code"]
    assert second.data.get("replayed") is True


def test_audit_history_is_recorded_per_agent(db, operator, approver):
    workflow = create_workflow(db, user=operator, request_text=ONBOARDING_REQUEST, start=False)
    run_to_completion(db, workflow, approver)
    entries = list(db.scalars(select(AuditLog).where(AuditLog.workflow_id == workflow.id).order_by(AuditLog.id)))
    assert len(entries) > 15
    assert {entry.agent_name for entry in entries} >= {"planner", "hr", "it", "document", "execution", "approval"}
    assert all(entry.created_at for entry in entries)
