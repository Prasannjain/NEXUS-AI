"""Response shaping for workflow payloads."""
from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .graph.orchestrator import TERMINAL_TASK_STATES
from .graph.state import STAGES
from .models import AgentExecution, Approval, AuditLog, GeneratedDocument, ToolCall, Workflow, WorkflowTask


def task_counts(db: Session, workflow_id: str) -> dict[str, int]:
    rows = list(db.scalars(select(WorkflowTask.status).where(WorkflowTask.workflow_id == workflow_id)))
    counts = dict(Counter(rows))
    counts.setdefault("total", len(rows))
    return counts


def pending_approval_ids(db: Session, workflow_id: str) -> list[str]:
    return [
        row.id
        for row in db.scalars(
            select(Approval).where(Approval.workflow_id == workflow_id, Approval.status == "pending")
        )
    ]


def workflow_out(db: Session, workflow: Workflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "title": workflow.title or workflow.request_text[:120],
        "request_text": workflow.request_text,
        "category": workflow.category,
        "status": workflow.status,
        "current_stage": workflow.current_stage,
        "active_agent": workflow.active_agent,
        "progress": workflow.progress,
        "requester": workflow.user.email if workflow.user else "",
        "created_at": workflow.created_at,
        "started_at": workflow.started_at,
        "finished_at": workflow.finished_at,
        "duration_seconds": workflow.duration_seconds,
        "result_summary": workflow.result_summary,
        "error_message": workflow.error_message,
        "pending_approvals": len(pending_approval_ids(db, workflow.id)),
        "task_counts": task_counts(db, workflow.id),
        "llm_provider": workflow.llm_provider,
    }


def stage_status(index: int, workflow: Workflow, tasks: list[WorkflowTask], approvals: list[Approval]) -> str:
    """Derive the monitor colour for one of the twelve architecture stages."""
    statuses = [task.status for task in tasks]
    terminal = sum(1 for status in statuses if status in TERMINAL_TASK_STATES)
    finished = workflow.status in ("completed", "completed_with_exceptions", "rejected", "failed", "cancelled")
    awaiting = workflow.status == "awaiting_approval"

    if index == 0:
        return "completed"
    if index == 1:
        return "completed"
    if index == 2:
        return "completed" if workflow.status != "queued" else "running"
    if index == 3:
        return "completed" if workflow.plan else ("running" if workflow.status != "queued" else "pending")
    if index == 4:
        if not tasks:
            return "pending"
        return "completed" if finished else "running"
    if index == 5:
        if not tasks:
            return "pending"
        if terminal == len(tasks):
            return "completed"
        return "running" if terminal or statuses else "pending"
    if index == 6:
        if not any(task.attempts for task in tasks):
            return "pending"
        return "completed" if finished else "running"
    if index == 7:
        if not approvals:
            return "pending"
        if awaiting or any(approval.status == "pending" for approval in approvals):
            return "waiting"
        return "completed"
    if index == 8:
        if not any(task.attempts for task in tasks):
            return "pending"
        if awaiting:
            return "waiting"
        return "completed" if finished else "running"
    if index == 9:
        if any(task.status == "retrying" for task in tasks):
            return "running"
        if any(task.status == "failed" for task in tasks):
            return "failed"
        if any(task.attempts > 1 for task in tasks):
            return "completed"
        return "pending"
    if index == 10:
        return "completed" if tasks else "pending"
    return "completed" if workflow.final_report else ("pending" if not finished else "running")


def build_timeline(db: Session, workflow: Workflow) -> list[dict[str, Any]]:
    tasks = list(db.scalars(select(WorkflowTask).where(WorkflowTask.workflow_id == workflow.id).order_by(WorkflowTask.seq)))
    approvals = list(db.scalars(select(Approval).where(Approval.workflow_id == workflow.id)))
    current = workflow.current_stage
    timeline = []
    for index, stage in enumerate(STAGES):
        status = stage_status(index, workflow, tasks, approvals)
        timeline.append(
            {
                **stage,
                "status": status,
                "is_current": stage["label"] == current,
                "detail": _stage_detail(stage["key"], workflow, tasks, approvals),
            }
        )
    return timeline


def _stage_detail(key: str, workflow: Workflow, tasks: list[WorkflowTask], approvals: list[Approval]) -> str:
    if key == "agents":
        agents = sorted({task.agent_name for task in tasks})
        return f"{len(tasks)} task(s) across {', '.join(agents) or 'no agents'}"
    if key == "approval":
        decided = [a for a in approvals if a.status != "pending"]
        return f"{len(decided)} decided, {len(approvals) - len(decided)} waiting" if approvals else "No sensitive action in this plan"
    if key == "recovery":
        retried = [task.task_id for task in tasks if task.attempts > 1]
        failed = [task.task_id for task in tasks if task.status == "failed"]
        if failed:
            return f"Failed: {', '.join(failed)}"
        return f"Recovered after backoff: {', '.join(retried)}" if retried else "No failures recorded"
    if key == "report":
        return workflow.result_summary or "Report generated when the workflow settles"
    if key == "orchestrator":
        return f"Progress {workflow.progress:.0f}%"
    if key == "backend":
        return f"Workflow id {workflow.id}"
    if key == "planner":
        plan = workflow.plan or {}
        return plan.get("rationale", "Waiting for the planner")[:200]
    if key == "tool_registry":
        return f"{len([t for t in tasks if t.attempts])} authorised tool call(s)"
    if key == "execution":
        return f"{len([t for t in tasks if t.status == 'completed'])}/{len(tasks) or 0} task(s) executed"
    if key == "audit":
        return "Every decision is written to the append-only trail"
    if key == "user_input":
        return workflow.request_text[:160]
    if key == "command_center":
        return workflow.category
    return ""


def workflow_detail(db: Session, workflow: Workflow) -> dict[str, Any]:
    payload = workflow_out(db, workflow)
    tasks = list(db.scalars(select(WorkflowTask).where(WorkflowTask.workflow_id == workflow.id).order_by(WorkflowTask.seq)))
    approvals = list(db.scalars(select(Approval).where(Approval.workflow_id == workflow.id).order_by(Approval.id)))
    executions = list(
        db.scalars(select(AgentExecution).where(AgentExecution.workflow_id == workflow.id).order_by(AgentExecution.id))
    )
    documents = list(db.scalars(select(GeneratedDocument).where(GeneratedDocument.workflow_id == workflow.id)))
    calls = list(db.scalars(select(ToolCall).where(ToolCall.workflow_id == workflow.id).order_by(ToolCall.id)))
    audit_count = len(list(db.scalars(select(AuditLog.id).where(AuditLog.workflow_id == workflow.id))))

    payload.update(
        {
            "tasks": [
                {
                    "task_id": task.task_id,
                    "seq": task.seq,
                    "description": task.description,
                    "agent_name": task.agent_name,
                    "tool_name": task.tool_name,
                    "arguments": task.arguments or {},
                    "depends_on": task.depends_on or [],
                    "requires_approval": task.requires_approval,
                    "risk_level": task.risk_level,
                    "status": task.status,
                    "output_summary": task.output_summary,
                    "result": task.result,
                    "error": task.error,
                    "attempts": task.attempts,
                    "started_at": task.started_at,
                    "finished_at": task.finished_at,
                }
                for task in tasks
            ],
            "approvals": [
                {
                    "id": approval.id,
                    "workflow_id": approval.workflow_id,
                    "task_id": approval.task_id,
                    "agent_name": approval.agent_name,
                    "action": approval.action,
                    "details": approval.details or {},
                    "risk_level": approval.risk_level,
                    "policy_reason": approval.policy_reason,
                    "status": approval.status,
                    "requested_at": approval.requested_at,
                    "decided_at": approval.decided_at,
                    "decided_by": approval.decided_by,
                    "comment": approval.comment,
                }
                for approval in approvals
            ],
            "executions": [
                {
                    "id": execution.id,
                    "agent_name": execution.agent_name,
                    "task_id": execution.task_id,
                    "node": execution.node,
                    "status": execution.status,
                    "decision": execution.decision,
                    "input_summary": execution.input_summary,
                    "output_summary": execution.output_summary,
                    "error": execution.error,
                    "duration_ms": execution.duration_ms,
                    "created_at": execution.created_at,
                }
                for execution in executions
            ],
            "documents": [
                {
                    "id": document.id,
                    "title": document.title,
                    "doc_type": document.doc_type,
                    "storage_path": document.storage_path,
                    "file_size": document.file_size,
                    "created_at": document.created_at,
                }
                for document in documents
            ],
            "tool_calls": [
                {
                    "tool_name": call.tool_name,
                    "task_id": call.task_id,
                    "agent_name": call.agent_name,
                    "status": call.status,
                    "idempotency_key": call.idempotency_key,
                    "duration_ms": call.duration_ms,
                    "summary": (call.result or {}).get("summary", ""),
                    "created_at": call.created_at,
                }
                for call in calls
            ],
            "timeline": build_timeline(db, workflow),
            "audit_entries": audit_count,
            "final_report": workflow.final_report,
        }
    )
    return payload
