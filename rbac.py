"""Role-based access control definitions shared by the API and the orchestrator."""
from __future__ import annotations

ROLE_DEFINITIONS: list[dict] = [
    {
        "name": "admin",
        "description": "Platform administrator. Can approve any action and manage the registry.",
        "permissions": ["*"],
    },
    {
        "name": "approver",
        "description": "Reviews checkpoints and may grant elevated capabilities to a workflow.",
        "permissions": [
            "workflows.view",
            "workflows.create",
            "approvals.view",
            "approvals.decide",
            "hr.read",
            "hr.write",
            "it.read",
            "it.account.write",
            "it.identity.write",
            "finance.read",
            "finance.payment.write",
            "document.read",
            "document.write",
            "crm.read",
            "crm.write",
            "notifications.send",
            "tools.view",
            "tools.execute",
            "integrations.view",
            "audit.view",
            "reports.view",
            "agents.view",
        ],
    },
    {
        "name": "operator",
        "description": "Business requester. Starts workflows and monitors them; cannot self-approve.",
        "permissions": [
            "workflows.view",
            "workflows.create",
            "approvals.view",
            "hr.read",
            "hr.write",
            "it.read",
            "it.account.write",
            "document.read",
            "document.write",
            "crm.read",
            "crm.write",
            "finance.read",
            "notifications.send",
            "tools.view",
            "tools.execute",
            "integrations.view",
            "audit.view",
            "reports.view",
            "agents.view",
        ],
    },
    {
        "name": "viewer",
        "description": "Read-only access to dashboards, reports and audit history.",
        "permissions": ["workflows.view", "approvals.view", "agents.view", "tools.view",
                        "integrations.view", "audit.view", "reports.view"],
    },
]

ROLE_PERMISSIONS: dict[str, list[str]] = {role["name"]: role["permissions"] for role in ROLE_DEFINITIONS}


def role_allows(permissions: list[str], required: str) -> bool:
    return "*" in permissions or required in permissions


def requester_permissions(user) -> list[str]:
    """Capability grants a workflow inherits from its requester's role.

    Which *agent* may call a tool is enforced separately by the registry, so the
    two checks stay independent.
    """
    return sorted(set(user.role.permissions if user and user.role else []))
