#!/usr/bin/env python3
"""Validate the exported n8n workflows without needing n8n installed.

Checks the things that actually break an import:
  - required top-level keys present
  - every node has id / name / type / typeVersion / position
  - node ids are unique
  - every connection endpoint refers to a node that exists
  - no credentialed node is left enabled

This exists because the workflow these were rebuilt from was missing
`connections` and `typeVersion` entirely, so it could not be imported or run
at all. A JSON file that parses is not the same as a workflow that works.

Usage:  python3 validate_workflows.py
Exit:   0 all valid, 1 problems found
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
WORKFLOWS = HERE / "workflows"

REQUIRED_TOP = ("name", "nodes", "connections", "settings")
REQUIRED_NODE = ("id", "name", "type", "typeVersion", "position")

# Node types that need a credential the viewer must supply. These must ship
# disabled or the workflow cannot run without secrets.
CREDENTIALED = {
    "n8n-nodes-base.googleSheets",
    "n8n-nodes-base.gmail",
    "n8n-nodes-base.hubspot",
    "n8n-nodes-base.postgres",
    "n8n-nodes-base.mysql",
    "n8n-nodes-base.slack",
}


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        wf = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"not valid JSON: {exc}"]

    for key in REQUIRED_TOP:
        if key not in wf:
            problems.append(f"missing top-level key: {key}")
    if problems:
        return problems

    names: set[str] = set()
    seen_ids: set[str] = set()

    for node in wf["nodes"]:
        name = node.get("name", "<unnamed>")
        for field in REQUIRED_NODE:
            if field not in node:
                problems.append(f"node {name!r} missing required field {field!r}")
        if not isinstance(node.get("position"), list) or len(node.get("position", [])) != 2:
            problems.append(f"node {name!r} position must be [x, y]")
        node_id = node.get("id")
        if node_id in seen_ids:
            problems.append(f"duplicate node id {node_id!r}")
        seen_ids.add(node_id)
        if name in names:
            problems.append(f"duplicate node name {name!r}")
        names.add(name)

        if node.get("type") in CREDENTIALED and not node.get("disabled"):
            problems.append(
                f"node {name!r} needs a credential but is enabled — "
                "ship it disabled so the workflow imports without secrets"
            )

    for src, conn in wf["connections"].items():
        if src not in names:
            problems.append(f"connection source {src!r} is not a node")
        branches = conn.get("main", [])
        if not branches:
            problems.append(f"connection {src!r} has no main branches")
        for branch in branches:
            for link in branch:
                target = link.get("node")
                if target not in names:
                    problems.append(f"connection {src!r} -> unknown node {target!r}")

    # A workflow where nothing is reachable from a trigger cannot do anything.
    reachable: set[str] = set()
    queue = [
        n["name"]
        for n in wf["nodes"]
        if "trigger" in n.get("type", "").lower() or "webhook" in n.get("type", "").lower()
    ]
    edges = {
        src: [l["node"] for br in conn.get("main", []) for l in br]
        for src, conn in wf["connections"].items()
    }
    while queue:
        node = queue.pop()
        if node in reachable:
            continue
        reachable.add(node)
        queue.extend(edges.get(node, []))
    orphans = [
        wf["nodes"][i]["name"]
        for i, n in enumerate(wf["nodes"])
        if n["name"] not in reachable and "stickynote" not in n.get("type", "").lower()
    ]
    if orphans:
        problems.append(f"nodes unreachable from any trigger: {orphans}")

    return problems


def main() -> int:
    files = sorted(WORKFLOWS.glob("*.json"))
    if not files:
        print(f"no workflows found in {WORKFLOWS}")
        return 1

    failed = False
    for path in files:
        problems = check(path)
        if problems:
            failed = True
            print(f"FAIL  {path.name}")
            for p in problems:
                print(f"        - {p}")
        else:
            wf = json.loads(path.read_text(encoding="utf-8"))
            nodes = len(wf["nodes"])
            disabled = sum(1 for n in wf["nodes"] if n.get("disabled"))
            print(f"OK    {path.name}  ({nodes} nodes, {disabled} credentialed/disabled)")

    print()
    print("all workflows valid" if not failed else "problems found")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
