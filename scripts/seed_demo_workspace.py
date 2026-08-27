"""Seed a ready-to-demo Tenacious workspace into the engine database.

Creates the workspace (playbook built from tenacious_sales_data/seed), an
admin user, one campaign, and the NovaPay prospect with its real enrichment
signals — so the full flow (compose → judge → approve → send-to-sink →
reply → booking) can be demonstrated immediately after `uvicorn server:app`.

Usage:
    python scripts/seed_demo_workspace.py --email you@example.com --password <pw>
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from sqlalchemy import select  # noqa: E402

from engine.db import Base, db_session, get_engine  # noqa: E402
from engine.models import Campaign, Prospect, User, Workspace  # noqa: E402
from engine.security import hash_password  # noqa: E402

SEED = BASE / "tenacious_sales_data" / "seed"


def _read(name: str, limit: int = 4000) -> str:
    path = SEED / name
    return path.read_text()[:limit] if path.exists() else ""


def build_playbook() -> dict:
    bench = {}
    bench_path = SEED / "bench_summary.json"
    if bench_path.exists():
        bench = json.loads(bench_path.read_text())
    capacity_lines = [
        f"{stack}: {info.get('available_engineers', 0)} engineers available, "
        f"deploy in {info.get('time_to_deploy_days', '?')} days"
        for stack, info in (bench.get("stacks") or {}).items()
    ]
    # Tone examples: the three Tenacious email sequences (cold / warm /
    # re-engagement) — the composer treats them as style references.
    sequences = []
    seq_dir = SEED / "email_sequences"
    if seq_dir.is_dir():
        for path in sorted(seq_dir.glob("*.md")):
            sequences.append(f"## {path.stem}\n{path.read_text()[:900]}")
    return {
        "company_name": "Tenacious Consulting and Outsourcing",
        "company_description": (
            "Tenacious provides managed talent outsourcing and project "
            "consulting to B2B tech companies."
        ),
        "value_proposition": (
            "We help B2B tech companies scale engineering and AI capacity "
            "quickly with vetted, managed teams — without long hiring cycles."
        ),
        "icp_definition": _read("icp_definition.md"),
        "style_guide": _read("style_guide.md"),
        "capacity_notes": "\n".join(capacity_lines)
        + ("\n" + bench.get("honesty_constraint", "") if bench else ""),
        "pricing_notes": _read("pricing_sheet.md", 1500),
        "case_studies": _read("case_studies.md", 3000),
        "examples": "\n\n".join(sequences)[:2800],
        "sign_off": "Alex Chen, Senior Engagement Manager, Tenacious Consulting",
        "support_contact": "hello@tenacious.dev",
    }


async def main(email: str, password: str) -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db_session() as db:
        existing = (
            await db.execute(select(Workspace).where(Workspace.slug == "tenacious"))
        ).scalar_one_or_none()
        if existing:
            print("Workspace 'tenacious' already exists — nothing to do.")
            return

        workspace = Workspace(
            name="Tenacious Consulting",
            slug="tenacious",
            from_name="Tenacious Consulting",
            playbook=build_playbook(),
        )
        db.add(workspace)
        await db.flush()

        db.add(User(
            workspace_id=workspace.id,
            email=email.lower().strip(),
            name="Demo Admin",
            password_hash=hash_password(password),
            role="admin",
        ))

        campaign = Campaign(
            workspace_id=workspace.id,
            name="Fintech Series B outreach",
            status="draft",  # activate from the dashboard
            require_approval=True,
            sequence=[
                {"day_offset": 3, "angle": "share the relevant case study"},
                {"day_offset": 7, "angle": "brief final check-in, easy opt-out"},
            ],
        )
        db.add(campaign)
        await db.flush()

        brief_path = BASE / "data" / "hiring_signal_brief_novapay.json"
        signals = {}
        if brief_path.exists():
            signals = json.loads(brief_path.read_text()).get("signals", {})
        db.add(Prospect(
            workspace_id=workspace.id,
            campaign_id=campaign.id,
            email="jordan.reyes@novapay.example",
            name="Jordan Reyes",
            company="NovaPay Technologies",
            title="VP Engineering",
            signals=signals,
            stage="enriched",
        ))
        print(
            "Seeded workspace 'tenacious' with admin "
            f"{email} — log in at /login, review Settings, then activate the "
            "campaign to see drafts appear in Approvals."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()
    if len(args.password) < 10:
        raise SystemExit("Password must be at least 10 characters")
    asyncio.run(main(args.email, args.password))
