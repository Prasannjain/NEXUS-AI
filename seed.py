"""Reference-data seeding: roles, users, agents and the tool catalog.

No workflows are invented here - every workflow you see in the UI was produced
by actually running the orchestrator.
"""
from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents.catalog import AGENTS
from .config import settings
from .database import init_db, session_scope
from .models import Agent, Role, User
from .rbac import ROLE_DEFINITIONS
from .security import hash_password
from .tools.registry import sync_catalog

# Synthetic demo credentials. Override DEMO_PASSWORD in .env for anything but a
# local sandbox; the accounts hold no real-world access.
DEMO_USERS = [
    ("admin@nexus-ai.example", "Dana Whitfield", "admin", "Platform Operations"),
    ("approver@nexus-ai.example", "Samuel Okonjo", "approver", "Finance Control"),
    ("operator@nexus-ai.example", "Leena Kapoor", "operator", "People Operations"),
    ("viewer@nexus-ai.example", "Tomas Berg", "viewer", "Internal Audit"),
]


def demo_password() -> str:
    return os.getenv("DEMO_PASSWORD", "NexusDemo2026!")


def seed(db: Session | None = None) -> dict[str, int]:
    owns = db is None
    db = db or session_scope()
    counts = {"roles": 0, "users": 0, "agents": 0}
    try:
        existing_roles = {role.name: role for role in db.scalars(select(Role))}
        for definition in ROLE_DEFINITIONS:
            role = existing_roles.get(definition["name"])
            if role is None:
                db.add(Role(**definition))
            else:
                role.description = definition["description"]
                role.permissions = definition["permissions"]
            counts["roles"] += 1
        db.commit()

        roles = {role.name: role for role in db.scalars(select(Role))}
        password = demo_password()
        for email, name, role_name, department in DEMO_USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                db.add(
                    User(
                        email=email,
                        full_name=name,
                        role_id=roles[role_name].id,
                        department=department,
                        hashed_password=hash_password(password),
                    )
                )
                counts["users"] += 1
            else:
                # Keep the demo account usable if DEMO_PASSWORD changed between runs.
                user.hashed_password = hash_password(password)
        db.commit()

        existing_agents = {agent.name: agent for agent in db.scalars(select(Agent))}
        for spec in AGENTS:
            row = existing_agents.get(spec.name)
            payload = {
                "name": spec.name,
                "display_name": spec.display_name,
                "description": spec.description,
                "capabilities": spec.capabilities,
                "allowed_tools": spec.allowed_tools,
            }
            if row is None:
                db.add(Agent(**payload))
            else:
                for key, value in payload.items():
                    setattr(row, key, value)
            counts["agents"] += 1
        db.commit()

        counts.update({"tools": sync_catalog(db)["tools"]})
        return counts
    finally:
        if owns:
            db.close()


def bootstrap() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(settings.database_url.split(":///")[-1])) or ".", exist_ok=True)
    init_db()
    seed()
