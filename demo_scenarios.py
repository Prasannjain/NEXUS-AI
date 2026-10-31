"""End-to-end demo runner for NEXUS AI.

Drives the three reference scenarios over HTTP exactly the way the web client
does: sign in, submit a natural-language request, watch the LangGraph stages
advance, approve every human checkpoint through the approvals API, and print the
final report. Requires a running backend (uvicorn or docker compose).

    cd backend
    ../.venv/Scripts/python scripts/demo_scenarios.py            # Windows venv
    .venv/bin/python scripts/demo_scenarios.py                   # POSIX venv
    python scripts/demo_scenarios.py --base-url http://localhost:8000

By default it approves checkpoints; ``--reject`` rejects the first checkpoint of
each workflow so the rejection and rollback path is visible too.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

TERMINAL = {"completed", "completed_with_exceptions", "rejected", "failed", "cancelled"}

SCENARIOS = [
    (
        "Employee onboarding (12-step reference scenario)",
        "Onboard Anita Verma as a Senior Data Analyst in the Finance Department "
        "starting 2026-11-16. Generate the offer letter and onboarding pack, set up "
        "her email and SSO identity, grant access to the analytics tools, reserve a "
        "laptop and notify her manager.",
        "employee_onboarding",
    ),
    (
        "Invoice processing",
        "Process invoice INV-88214 from Acme Office Supplies for EUR 1,290.50. "
        "Extract the data, validate it, check for duplicates and create the payment request.",
        "invoice_processing",
    ),
    (
        "Customer support request",
        "Customer Beacon Retail Group asks where order ORD-77301 is; ticket TCK-44102 "
        "is late. Look up the order, update the ticket and log the resolution.",
        "customer_request",
    ),
]


def _fail(message: str) -> None:
    print(f"\n[demo] {message}", file=sys.stderr)
    sys.exit(1)


def run_scenario(
    client: httpx.Client, title: str, request_text: str, category: str, *, reject: bool, timeout: float
) -> str:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}\nRequest: {request_text}\n")

    preview = client.post("/api/workflows/preview-plan", json={"request_text": request_text, "category": category})
    if preview.status_code != 200:
        _fail(f"plan preview failed: {preview.text}")
    plan = preview.json()
    print(f"Planner -> {plan['task_count']} task(s), agents: {', '.join(plan['agents'])}")
    for task in plan["tasks"]:
        gate = " [approval checkpoint]" if task["requires_approval"] else ""
        print(f"  {task['task_id']:>4} {task['agent']:<9} {task['tool']:<34}{gate} deps={task.get('depends_on') or []}")

    created = client.post("/api/workflows", json={"request_text": request_text, "category": category})
    if created.status_code not in (200, 201):
        _fail(f"submit failed: {created.text}")
    workflow_id = created.json()["id"]
    print(f"\nSubmitted as {workflow_id}")

    deadline = time.monotonic() + timeout
    decided: set[str] = set()
    rejections_left = 1 if reject else 0
    seen_stage = ""
    while time.monotonic() < deadline:
        detail = client.get(f"/api/workflows/{workflow_id}").json()
        status = detail["status"]

        if detail["current_stage"] != seen_stage:
            seen_stage = detail["current_stage"]
            print(f"  stage: {seen_stage:<28} status={status:<20} tasks={detail['progress']}")

        if status == "awaiting_approval":
            pending = client.get("/api/approvals", params={"status": "pending", "limit": 200}).json()
            for approval in pending["items"]:
                if approval["workflow_id"] != workflow_id or approval["id"] in decided:
                    continue
                if not approval["can_decide"]:
                    _fail(f"the signed-in role may not decide {approval['id']} - use admin@nexus-ai.example")
                action = "reject" if rejections_left else "approve"
                rejections_left -= 1 if rejections_left else 0
                comment = (
                    "Rejected by demo runner to show the rollback and dependent-task path."
                    if action == "reject"
                    else f"Approved by demo runner: {approval['risk_level']} risk, {approval['side_effect']} side effect."
                )
                outcome = client.post(
                    f"/api/approvals/{approval['id']}/decide", json={"action": action, "comment": comment}
                )
                if outcome.status_code != 200:
                    _fail(f"decision failed for {approval['id']}: {outcome.text}")
                decided.add(approval["id"])
                verb = "approved" if action == "approve" else "rejected"
                print(
                    f"  checkpoint {verb}: {approval['tool']} "
                    f"({approval['risk_level']} risk, requires {approval['required_permission']})"
                )
            continue

        if status in TERMINAL:
            report = client.get(f"/api/workflows/{workflow_id}/report").json()
            audit_entries = client.get(f"/api/audit/workflow/{workflow_id}").json()
            print(f"\nFinal status : {status}")
            print(f"Headline     : {report.get('headline', '')}")
            print(
                f"Tasks        : {len(report.get('completed_tasks', []))}/{len(report.get('tasks', []))} completed, "
                f"{len(report.get('failed_tasks', []))} failed, {len(report.get('skipped_tasks', []))} skipped"
            )
            print(f"Tool calls   : {len(report.get('tool_executions', []))}")
            print(f"Documents    : {len(report.get('documents', []))}")
            print(f"Approvals    : {len(decided)} checkpoint(s) decided")
            print(f"Audit entries: {len(audit_entries) if isinstance(audit_entries, list) else audit_entries['total']}")
            if report.get("simulation_notice"):
                print(f"Sandbox note : {report['simulation_notice']}")
            markdown = client.get(f"/api/reports/{workflow_id}.md").text
            print(f"Report markdown: {len(markdown)} characters available at /api/reports/{workflow_id}.md")
            return status

        time.sleep(0.6)

    _fail(f"{workflow_id} did not reach a terminal state within {timeout:g}s")
    return "timeout"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NEXUS AI demo scenarios against a live API.")
    parser.add_argument("--base-url", default=os.getenv("NEXUS_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--email", default=os.getenv("DEMO_EMAIL", "admin@nexus-ai.example"))
    parser.add_argument(
        "--password",
        default=os.getenv("DEMO_PASSWORD") or os.getenv("NEXUS_DEMO_PASSWORD") or "NexusDemo2026!",
    )
    parser.add_argument("--timeout", type=float, default=240.0, help="Per-workflow wall clock budget in seconds.")
    parser.add_argument("--reject", action="store_true", help="Reject the first checkpoint of each workflow.")
    parser.add_argument(
        "--scenario",
        choices=["onboarding", "invoice", "support", "all"],
        default="all",
        help="Which reference scenario to run.",
    )
    args = parser.parse_args()

    selected = {
        "onboarding": SCENARIOS[:1],
        "invoice": SCENARIOS[1:2],
        "support": SCENARIOS[2:],
        "all": SCENARIOS,
    }[args.scenario]

    with httpx.Client(base_url=args.base_url, timeout=30.0) as client:
        try:
            health = client.get("/api/health").json()
        except httpx.HTTPError as error:
            _fail(f"API unreachable at {args.base_url}: {error}\nStart it with `uvicorn app.main:app --port 8000`.")
        print(
            f"API {health['status']} | provider={health['llm_provider']} | "
            f"db={health['database_dialect']} | {health['simulated_integrations'] and 'sandbox integrations'}"
        )

        login = client.post("/api/auth/login", json={"email": args.email, "password": args.password})
        if login.status_code != 200:
            _fail(f"login failed for {args.email}: {login.text}")
        client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
        me = login.json()["user"]
        print(f"Signed in as {me['full_name']} <{me['email']}> role={me['role']['name']}")

        results = {}
        for title, request_text, category in selected:
            results[category] = run_scenario(client, title, request_text, category, reject=args.reject, timeout=args.timeout)

        print(f"\n{'=' * 78}\nSummary\n{'=' * 78}")
        for category, status in results.items():
            print(f"  {category:<22} {status}")
        print("\nOpen the web UI to inspect the runs, approvals, audit trail and reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
