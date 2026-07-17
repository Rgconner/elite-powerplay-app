#!/usr/bin/env python3
"""One-time utility: create the first admin user.

Usage (run from the backend/ directory):
    python3 create_admin.py
or with custom credentials:
    ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=s3cr3t python3 create_admin.py
"""

import os
import sys

# Allow running from the backend/ directory without installing the package.
sys.path.insert(0, os.path.dirname(__file__))

# Ensure DATABASE_URL is set (falls back to the dev default).
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = (
        "postgresql://app:dumbbunny@192.168.11.6:5432/power-play"
    )

from db.session import SessionLocal, engine  # noqa: E402
from models.models import Base, AdminUser    # noqa: E402
from routers.auth import hash_password       # noqa: E402

email    = os.environ.get("ADMIN_EMAIL",    "admin@local")
password = os.environ.get("ADMIN_PASSWORD", "changeme")

# Create tables if they don't exist yet (idempotent).
Base.metadata.create_all(bind=engine)

db = SessionLocal()
try:
    existing = db.query(AdminUser).filter(AdminUser.email == email).first()
    if existing:
        print(f"[!] Admin user '{email}' already exists — no changes made.")
    else:
        db.add(AdminUser(email=email, hashed_password=hash_password(password)))
        db.commit()
        print(f"[✓] Admin user '{email}' created successfully.")
        print(    "    Change the password after first login.")
finally:
    db.close()
