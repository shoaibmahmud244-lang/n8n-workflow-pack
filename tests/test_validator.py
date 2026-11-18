from __future__ import annotations

import json
from pathlib import Path

from scripts.lead_intake import process_submissions
from validate_workflows import WORKFLOWS, check


def test_shipped_workflows_are_valid() -> None:
    files = sorted(WORKFLOWS.glob("*.json"))
    assert len(files) == 2
    for f in files:
        assert check(f) == [], f"Unexpected errors in {f.name}"


def test_validator_catches_enabled_credentialed_node(tmp_path: Path) -> None:
    wf = json.loads((WORKFLOWS / "01-form-intake-to-crm.json").read_text("utf-8"))
    for node in wf["nodes"]:
        if node["type"] == "n8n-nodes-base.gmail":
            node["disabled"] = False
    bad_file = tmp_path / "bad.json"
    bad_file.write_text(json.dumps(wf), encoding="utf-8")

    problems = check(bad_file)
    assert any("needs a credential but is enabled" in p for p in problems)


def test_validator_catches_orphan_node(tmp_path: Path) -> None:
    wf = json.loads((WORKFLOWS / "01-form-intake-to-crm.json").read_text("utf-8"))
    wf["nodes"].append(
        {
            "id": "orphan-1",
            "name": "Orphan Code",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [0, 0],
        }
    )
    bad_file = tmp_path / "orphan.json"
    bad_file.write_text(json.dumps(wf), encoding="utf-8")

    problems = check(bad_file)
    assert any("nodes unreachable from any trigger" in p for p in problems)


def test_lead_intake_idempotent_upsert(tmp_path: Path) -> None:
    subs = tmp_path / "subs.json"
    crm = tmp_path / "crm.csv"
    log = tmp_path / "run.log"
    subs.write_text(
        json.dumps(
            [
                {"name": "sarah chen", "email": "sarah@acme.io", "company": "acme", "budget": "$2k"},
                {"name": "Sarah Chen", "email": "SARAH@acme.io", "company": "Acme Corp", "budget": "$5k"},
                {"name": "bad", "email": "not-an-email"},
            ]
        ),
        encoding="utf-8",
    )
    stats1 = process_submissions(subs, crm, log)
    assert stats1 == {"inserted": 1, "updated": 1, "rejected": 1, "total": 1}

    stats2 = process_submissions(subs, crm, log)
    assert stats2 == {"inserted": 0, "updated": 2, "rejected": 1, "total": 1}
    assert "Acme Corp" in crm.read_text(encoding="utf-8")
    assert "------" in log.read_text(encoding="utf-8")
