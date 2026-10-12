#!/usr/bin/env python3
"""Explicit, non-destructive local demo account provisioning; never startup seeding."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/examples/lab-smart-factory.json")
    parser.add_argument("--credentials", type=Path, default=ROOT / ".run/lab-accounts.json")
    parser.add_argument("--database-url", help="Operational platform DB, not the raw telemetry intake DB")
    parser.add_argument("--sync-qualifications", action="store_true", help="Explicitly issue configured qualifications to matching existing generated operator accounts")
    args = parser.parse_args()
    args.config = args.config.resolve()
    args.credentials = args.credentials.resolve()
    # The launcher deliberately overrides legacy .env DATABASE_URL values.
    # Match that default; only an explicit CLI/environment override changes it.
    os.environ["DATABASE_URL"] = args.database_url or os.environ.get("DATABASE_URL") or "sqlite:///./manufacturing_platform.db"
    # Resolve the application's ordinary .env and SQLite defaults exactly as its launcher does.
    os.chdir(ROOT / "backend")
    from sqlalchemy import select
    from app.db import SessionLocal, create_schema
    from app.platform_auth import hash_password
    from app.platform_configuration import Graph, validate_specification
    from app.platform_models import User, UserQualification
    from app.platform_personnel import requirements, role_allows

    specification = json.loads(args.config.resolve().read_text())
    errors = validate_specification(specification)
    if errors:
        parser.error("Invalid configuration: " + "; ".join(errors))
    graph = Graph(specification)
    groups = sorted({(tuple(requirements(graph, entity["id"])["qualifications"]), tuple(requirements(graph, entity["id"])["skills"]))
                     for entity in specification["entities"] if entity["type"] == "stage"})
    accounts = [{"email": "admin@sml.local", "name": "Lab administrator", "role": "admin", "skills": [], "qualifications": []}]
    for number, (qualifications, skills) in enumerate(groups, 1):
        identifier = hashlib.sha256(json.dumps(qualifications or skills).encode()).hexdigest()[:10]
        labels = [graph.entity(item)["name"] for item in qualifications] if qualifications else list(skills)
        accounts.append({"email": f"operator-{identifier}@sml.local", "name": f"Operator {number}: {' / '.join(labels) or 'General'}"[:120],
                         "role": "operator", "skills": [] if qualifications else list(skills), "qualifications": list(qualifications)})
    destination = args.credentials.resolve()
    if not destination.is_relative_to(ROOT / ".run"):
        parser.error("Credentials must be saved under the ignored project .run directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    saved = json.loads(destination.read_text()) if destination.exists() else {"accounts": []}
    previous = {item["email"]: item for item in saved["accounts"]}
    create_schema()
    created = 0
    with SessionLocal() as db:
        administrator = None
        for account in accounts:
            existing = db.scalar(select(User).where(User.email == account["email"]))
            if existing:
                previous.setdefault(account["email"], {"email": account["email"], "status": "Existing account preserved; password unchanged"})
                user = existing
            else:
                password = secrets.token_urlsafe(18)
                user = User(**{key: value for key, value in account.items() if key != "qualifications"},
                            password_hash=hash_password(password), available=True, active=True)
                db.add(user)
                db.flush()
                previous[account["email"]] = {**account, "password": password}
                created += 1
            if account["role"] == "admin":
                if user.role != "admin" or not user.active:
                    parser.error("The existing generated administrator is not an active admin; resolve it manually")
                administrator = user
            if not existing or args.sync_qualifications:
                for qualification_id in account["qualifications"]:
                    if not role_allows(graph, user.role, qualification_id):
                        parser.error("A configured qualification is incompatible with the existing account role")
                    issued = db.get(UserQualification, (user.id, qualification_id))
                    if not issued:
                        db.add(UserQualification(user_id=user.id, qualification_id=qualification_id, assigned_by=administrator.id))
                    elif args.sync_qualifications:
                        issued.active = True
                        issued.assigned_by = administrator.id
        # Save before commit so new credentials cannot be lost after a successful DB write.
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump({"accounts": list(previous.values())}, stream, indent=2)
            stream.write("\n")
        db.commit()
    print(f"Created {created} accounts. Existing accounts were preserved.")
    print(f"Credentials saved locally to {destination} (permissions 600); do not share or commit this file.")


if __name__ == "__main__":
    main()
