#!/usr/bin/env python3
"""Idempotent lead intake script: validate -> true CSV upsert -> append audit log."""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIELDNAMES = ["name", "email", "company", "budget", "source", "updated_at"]
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")


def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email.strip().lower()))


def process_submissions(
    submissions_path: Path, crm_path: Path, log_path: Path
) -> dict[str, int]:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    lines: list[str] = [f"[{stamp}] TRIGGER: Batch intake started"]

    subs: list[dict[str, Any]] = json.loads(
        submissions_path.read_text(encoding="utf-8")
    )
    lines.append(f"[{stamp}] STEP 1: Loaded {len(subs)} submissions")

    contacts: dict[str, dict[str, str]] = {}
    if crm_path.exists():
        with crm_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                key = row["email"].strip().lower()
                contacts[key] = row

    inserted = updated = rejected = 0
    for sub in subs:
        email = str(sub.get("email", "")).strip().lower()
        name = str(sub.get("name", "")).strip().title()
        if not valid_email(email) or not name:
            rejected += 1
            continue

        record = {
            "name": name,
            "email": email,
            "company": str(sub.get("company", "")).strip().title(),
            "budget": str(sub.get("budget", "")).strip(),
            "source": "website-form",
            "updated_at": now_str,
        }
        if email in contacts:
            contacts[email] = record
            updated += 1
        else:
            contacts[email] = record
            inserted += 1

    lines.append(
        f"[{stamp}] STEP 2: Processed — {inserted} inserted, "
        f"{updated} updated, {rejected} rejected"
    )

    tmp_crm = crm_path.with_suffix(".csv.tmp")
    with tmp_crm.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(contacts.values())
    tmp_crm.replace(crm_path)

    with log_path.open("a", encoding="utf-8") as fh:
        if log_path.stat().st_size > 0:
            fh.write("-" * 60 + "\n")
        fh.write("\n".join(lines) + "\n")

    return {"inserted": inserted, "updated": updated, "rejected": rejected, "total": len(contacts)}
