"""HTTP API tests covering the full demonstration scenario."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

PASSWORD = "NexusTest123!"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as instance:
        yield instance


def login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def wait_for(client, workflow_id: str, predicate, token: str = "", timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        response = client.get(f"/api/workflows/{workflow_id}", headers=auth(token) if token else {})
        assert response.status_code == 200, response.text
        last = response.json()
        if predicate(last):
            return last
        time.sleep(0.25)
    raise AssertionError(f"workflow did not reach the expected state: {last.get('status')}")


def test_health_is_open(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["orchestrator"] == "LangGraph"
    assert payload["simulated_integrations"] is True


def test_login_rejects_bad_password(client):
    response = client.post("/api/auth/login", json={"email": "operator@nexus-ai.example", "password": "wrong"})
    assert response.status_code == 401


def test_protected_route_requires_token(client):
    assert client.get("/api/workflows").status_code in (401, 403)


def test_architecture_exposes_twelve_stages(client):
    stages = client.get("/api/architecture").json()["stages"]
    assert [stage["label"] for stage in stages] == [
        "User Input", "AI Command Center", "Backend Processing", "Planner Agent",
        "LangGraph Orchestrator", "Specialized AI Agents", "Tool Registry",
        "Human Approval", "Execution Agent", "Failure Recovery", "Audit Logging",
        "Final Report",
    ]


def approve_all_checkpoints(client, workflow_id: str, approver_token: str, requester_token: str) -> dict:
    """Approve every checkpoint the graph raises until the workflow settles.

    A snapshot can legitimately show ``awaiting_approval`` with nothing pending
    while the resumed run travels to the next checkpoint, so the loop waits for
    either a new pending approval or a terminal status.
    """
    settled = ("completed", "completed_with_exceptions", "rejected", "failed", "cancelled")

    def ready(payload: dict) -> bool:
        return any(approval["status"] == "pending" for approval in payload["approvals"]) or payload[
            "status"
        ] in settled

    detail = wait_for(client, workflow_id, ready, requester_token)
    for _ in range(12):
        pending = [approval for approval in detail["approvals"] if approval["status"] == "pending"]
        if not pending:
            return detail
        for approval in pending:
            response = client.post(
                f"/api/approvals/{approval['id']}/decide",
                headers=auth(approver_token),
                json={"action": "approve", "comment": "Verified against the sandbox policy"},
            )
            assert response.status_code == 200, response.text
        detail = wait_for(client, workflow_id, ready, requester_token)
    raise AssertionError("checkpoints did not drain")


def test_full_onboarding_scenario(client):
    operator = login(client, "operator@nexus-ai.example")
    admin = login(client, "admin@nexus-ai.example")

    submitted = client.post(
        "/api/workflows",
        headers=auth(operator),
        json={"request_text": "Onboard Rahul Sharma as a Software Engineer in the Engineering Department."},
    )
    assert submitted.status_code == 201, submitted.text
    workflow_id = submitted.json()["id"]

    paused = wait_for(client, workflow_id, lambda detail: detail["status"] == "awaiting_approval", operator)

    assert paused["pending_approvals"] >= 1
    assert paused["current_stage"] == "Human Approval"
    approval_ids = [approval["id"] for approval in paused["approvals"] if approval["status"] == "pending"]

    # The operator may see the queue but must not be able to clear it.
    forbidden = client.post(
        f"/api/approvals/{approval_ids[0]}/decide", headers=auth(operator), json={"action": "approve"}
    )
    assert forbidden.status_code == 403

    finished = approve_all_checkpoints(client, workflow_id, admin, operator)

    assert finished["progress"] == 100.0
    assert {task["agent_name"] for task in finished["tasks"]} >= {"hr", "document", "it"}
    assert all(task["status"] == "completed" for task in finished["tasks"])
    assert finished["documents"], "the Document Agent must have produced artefacts"
    assert finished["tool_calls"]

    timeline = {stage["label"]: stage["status"] for stage in finished["timeline"]}
    assert timeline["Final Report"] == "completed"
    assert timeline["Human Approval"] == "completed"

    report = client.get(f"/api/workflows/{workflow_id}/report", headers=auth(operator)).json()
    assert report["original_request"].startswith("Onboard Rahul Sharma")
    assert report["approvals"], "approval history belongs in the report"
    assert report["tool_executions"]

    markdown = client.get(f"/api/workflows/{workflow_id}/report.md", headers=auth(operator))
    assert markdown.status_code == 200
    assert "Human approval history" in markdown.text

    notifications = client.get("/api/notifications", headers=auth(operator)).json()
    assert any("completed" in item["title"].lower() for item in notifications["items"])

    audit = client.get(
        "/api/audit", headers=auth(operator), params={"workflow_id": workflow_id, "limit": 500}
    ).json()
    assert audit["total"] > 15
    assert {"workflow_planned", "approval_granted", "tool_invoked"} <= {
        entry["event_type"] for entry in audit["items"]
    }


def test_monitor_events_feed(client):
    operator = login(client, "operator@nexus-ai.example")
    listing = client.get("/api/workflows", headers=auth(operator)).json()
    workflow_id = listing["items"][0]["id"]
    feed = client.get(f"/api/workflows/{workflow_id}/events", headers=auth(operator)).json()
    assert {"status", "stage", "tasks", "timeline", "progress"} <= set(feed)
    assert len(feed["timeline"]) == 12


def test_approver_can_reject_and_report_reflects_it(client):
    operator = login(client, "operator@nexus-ai.example")
    admin = login(client, "admin@nexus-ai.example")
    submitted = client.post(
        "/api/workflows",
        headers=auth(operator),
        json={"request_text": "Onboard Priya Menon as a Lead Engineer in the Engineering Department."},
    ).json()
    workflow_id = submitted["id"]
    paused = wait_for(client, workflow_id, lambda detail: detail["status"] == "awaiting_approval", operator)
    approval_id = [a["id"] for a in paused["approvals"] if a["status"] == "pending"][0]
    response = client.post(
        f"/api/approvals/{approval_id}/decide",
        headers=auth(admin),
        json={"action": "reject", "comment": "Headcount not approved for this quarter"},
    )
    assert response.status_code == 200
    finished = wait_for(client, workflow_id, lambda detail: detail["status"] in ("rejected", "completed_with_exceptions"), operator)
    assert finished["final_report"]["rejected_tasks"]
    assert finished["final_report"]["skipped_tasks"]


def test_invoice_workflow_requires_payment_approval(client):
    admin = login(client, "admin@nexus-ai.example")
    submitted = client.post(
        "/api/workflows",
        headers=auth(admin),
        json={"request_text": "Process invoice INV-88214 from Acme Office Supplies for EUR 1,290.50."},
    ).json()
    workflow_id = submitted["id"]
    paused = wait_for(client, workflow_id, lambda detail: detail["status"] == "awaiting_approval", admin)
    assert any("payment" in approval["action"].lower() for approval in paused["approvals"])
    finished = approve_all_checkpoints(client, workflow_id, admin, admin)
    tools = {call["tool_name"] for call in finished["tool_calls"]}
    assert "finance.create_payment_request" in tools
    assert "finance.detect_duplicate_invoice" in tools


def test_operator_can_run_the_invoice_scenario(client):
    """A business requester may drive invoice processing to completion.

    Invoice reads belong to the operator role; only the payment write stays
    behind an approval checkpoint that the operator cannot clear themselves.
    """
    operator = login(client, "operator@nexus-ai.example")
    admin = login(client, "admin@nexus-ai.example")
    submitted = client.post(
        "/api/workflows",
        headers=auth(operator),
        json={
            "request_text": "Process invoice INV-90512 from Acme Office Supplies for EUR 2,480.00 "
            "and schedule payment.",
            "category": "invoice_processing",
        },
    )
    assert submitted.status_code == 201, submitted.text
    workflow_id = submitted.json()["id"]
    finished = approve_all_checkpoints(client, workflow_id, admin, operator)
    assert finished["status"] in ("completed", "completed_with_exceptions"), finished["error_message"]
    tasks = {task["tool_name"]: task["status"] for task in finished["tasks"]}
    assert tasks["finance.extract_invoice_data"] == "completed"
    assert tasks["finance.create_payment_request"] == "completed"
    assert all(approval["status"] == "approved" for approval in finished["approvals"])
    assert finished["final_report"]["entities"]["vendor_name"] == "Acme Office Supplies"


def test_support_workflow_completes_without_approval(client):
    operator = login(client, "operator@nexus-ai.example")
    submitted = client.post(
        "/api/workflows",
        headers=auth(operator),
        json={"request_text": "Customer Beacon Retail Group asks where order ORD-77301 is; ticket TCK-44102 is late."},
    ).json()
    workflow_id = submitted["id"]
    finished = wait_for(client, workflow_id, lambda detail: detail["status"].startswith("completed"), operator)
    assert finished["status"] == "completed", finished["error_message"]
    assert any(call["tool_name"].startswith("crm.") for call in finished["tool_calls"])


def test_tool_registry_endpoints(client):
    admin = login(client, "admin@nexus-ai.example")
    tools = client.get("/api/tools", headers=auth(admin)).json()
    assert len(tools) >= 20
    assert all(tool["has_adapter"] for tool in tools)

    disabled = client.patch(
        f"/api/tools/{'it.setup_equipment'}", headers=auth(admin), json={"enabled": False}
    )
    assert disabled.status_code == 200 and disabled.json()["enabled"] is False
    restored = client.patch(
        "/api/tools/it.setup_equipment", headers=auth(admin), json={"enabled": True}
    )
    assert restored.json()["enabled"] is True

    forbidden = client.patch("/api/tools/it.setup_equipment", headers=auth(login(client, "operator@nexus-ai.example")), json={"enabled": False})
    assert forbidden.status_code == 403

    validation = client.post("/api/tools/hr.create_employee_record/validate", headers=auth(admin)).json()
    assert validation["schema_valid"] is True
    assert "full_name" in validation["required_fields"]


def test_registering_a_tool_requires_a_valid_schema(client):
    admin = login(client, "admin@nexus-ai.example")
    payload = {
        "name": "custom.export_report",
        "display_name": "Export scheduled report",
        "description": "Operator-registered placeholder adapter.",
        "integration_key": "document_storage",
        "input_schema": {"type": "object", "required": ["recipient"], "properties": {"recipient": {"type": "string"}}},
        "agent_scope": ["document"],
        "required_permission": "document.write",
        "enabled": False,
    }
    created = client.post("/api/tools", headers=auth(admin), json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["has_adapter"] is False
    duplicate = client.post("/api/tools", headers=auth(admin), json=payload)
    assert duplicate.status_code == 409
    bad_schema = client.post(
        "/api/tools",
        headers=auth(admin),
        json={**payload, "name": "custom.bad_schema", "input_schema": {"type": "not-a-real-type"}},
    )
    assert bad_schema.status_code == 422
    unknown_integration = client.post(
        "/api/tools", headers=auth(admin), json={**payload, "name": "custom.unknown", "integration_key": "sap"}
    )
    assert unknown_integration.status_code == 422


def test_integrations_report_simulation(client):
    operator = login(client, "operator@nexus-ai.example")
    integrations = client.get("/api/integrations", headers=auth(operator)).json()
    assert len(integrations) == 6
    assert all(item["is_simulated"] for item in integrations)
    checked = client.post("/api/integrations/hr_system/test", headers=auth(operator)).json()
    assert checked["simulated"] is True
    assert checked["tools"]


def test_agents_endpoint_reports_activity(client):
    operator = login(client, "operator@nexus-ai.example")
    agents = client.get("/api/agents", headers=auth(operator)).json()
    assert {agent["name"] for agent in agents} >= {"planner", "hr", "document", "it", "finance", "support", "approval", "audit", "execution"}
    hr = next(agent for agent in agents if agent["name"] == "hr")
    assert hr["tasks_completed"] > 0
    detail = client.get("/api/agents/hr", headers=auth(operator)).json()
    assert detail["recent_executions"]


def test_dashboard_and_reports(client):
    operator = login(client, "operator@nexus-ai.example")
    stats = client.get("/api/dashboard/stats", headers=auth(operator)).json()
    assert stats["counters"]["total_workflows"] >= 3
    assert stats["counters"]["success_rate"] is not None
    assert len(stats["daily_trend"]) == 14
    assert stats["recent_workflows"]
    reports = client.get("/api/reports", headers=auth(operator)).json()
    assert reports["summary"]["reports"] >= 3
    assert client.get("/api/reports/platform", headers=auth(operator)).json()["totals"]["tasks"] > 0


def test_audit_search_and_csv_export(client):
    operator = login(client, "operator@nexus-ai.example")
    search = client.get("/api/audit", headers=auth(operator), params={"q": "Rahul"}).json()
    assert search["total"] >= 1
    csv_response = client.get("/api/audit/export.csv", headers=auth(operator))
    assert csv_response.status_code == 200
    assert csv_response.text.startswith("id,timestamp_utc,workflow_id")


def test_settings_and_provider_switching(client):
    operator = login(client, "operator@nexus-ai.example")
    admin = login(client, "admin@nexus-ai.example")
    payload = client.get("/api/settings", headers=auth(operator)).json()
    names = {provider["name"] for provider in payload["llm"]["providers"]}
    assert {"gemini", "openai", "ollama", "none"} <= names
    assert payload["platform"]["orchestration"]["engine"] == "LangGraph"
    assert payload["llm"]["note"].lower().count("never") == 1

    refused = client.put("/api/settings/llm/provider", headers=auth(operator), json={"provider": "none"})
    assert refused.status_code == 403
    switched = client.put("/api/settings/llm/provider", headers=auth(admin), json={"provider": "none"})
    assert switched.status_code == 200
    tested = client.post("/api/settings/llm/test", headers=auth(admin), json={"provider": "none"}).json()
    assert tested["status"] == "offline_fallback"


def test_input_validation_and_planner_preview(client):
    operator = login(client, "operator@nexus-ai.example")
    short = client.post("/api/workflows", headers=auth(operator), json={"request_text": "hi"})
    assert short.status_code == 422
    preview = client.post(
        "/api/workflows/preview-plan",
        headers=auth(operator),
        json={"request_text": "Onboard Aisha Khan as a Data Analyst in the Finance Department."},
    ).json()
    assert preview["category"] == "employee_onboarding"
    assert preview["approval_checkpoints"]
    assert "Aisha Khan" in str(preview["entities"])


def test_viewer_cannot_start_workflows(client):
    viewer = login(client, "viewer@nexus-ai.example")
    response = client.post(
        "/api/workflows", headers=auth(viewer), json={"request_text": "Onboard Someone New as a Manager in Sales."}
    )
    assert response.status_code == 403


def test_cancelling_a_paused_workflow(client):
    operator = login(client, "operator@nexus-ai.example")
    submitted = client.post(
        "/api/workflows",
        headers=auth(operator),
        json={"request_text": "Onboard Viktor Rau as a Site Reliability Engineer in the Engineering Department."},
    ).json()
    workflow_id = submitted["id"]
    wait_for(client, workflow_id, lambda detail: detail["status"] == "awaiting_approval", operator)
    cancelled = client.post(f"/api/workflows/{workflow_id}/cancel", headers=auth(operator))
    assert cancelled.status_code == 200
    detail = client.get(f"/api/workflows/{workflow_id}", headers=auth(operator)).json()
    assert detail["status"] == "cancelled"
    history = client.get("/api/audit", headers=auth(operator), params={"workflow_id": workflow_id}).json()
    assert any(entry["event_type"] == "workflow_cancelled" for entry in history["items"])
