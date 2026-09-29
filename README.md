# n8n workflow pack

Two production-shaped n8n workflows. Both **import and run with zero
credentials** — every node that needs a secret ships disabled, so you can click
*Import from File* and see the graph immediately instead of a wall of red.

| Workflow | What it does |
|---|---|
| `01-form-intake-to-crm.json` | Public form → validate → reject bad leads → Sheets → auto-reply → CRM upsert |
| `02-scheduled-scrape-to-sheet.json` | Cron → scrape → normalise → diff against Postgres → append only what changed |

---

## Why these exist

Most n8n JSON shared publicly is a screenshot of a graph, not a file you can
import. This pack is the opposite: valid exports, verified by a script, with the
credential-dependent nodes disabled so the thing actually opens.

## Import them

**n8n → Workflows → Import from File → pick a `.json`**

Nothing else is required. To make a node live: connect the credential, fill in
the id it asks for, enable the node, test that node alone.

---

## Workflow 1 — form intake to CRM

```
POST /webhook/lead-intake  {name, email, message}
        │
        ▼
Validate + Split Name ──► Accepted?
        │                   ├─ true  ──► Auto-reply ──► Sheets Append ──► CRM Upsert
        │                   └─ false ──► Log Rejected
```

**Design decisions worth pointing at:**

- **Rejects go down a separate branch.** An invalid email never reaches Sheets
  or HubSpot. Rejections are logged rather than dropped, so a broken form is
  visible instead of invisible.
- **Surname is `parts.slice(1).join(' ')`**, not `parts[1]`. "Ada Byron King"
  becomes `firstname=Ada, lastname=Byron King` instead of silently dropping
  Byron. This is the kind of bug that ships and nobody notices for a year.
- **Message is truncated to 500 chars** so a pasted document cannot bloat the
  sheet or blow past an API limit.
- **CRM is an upsert, not a create.** Resubmitting the form updates the existing
  contact instead of creating a duplicate.

---

## Workflow 2 — scheduled scrape to sheet

```
Every 6 Hours ──► Fetch Page ──► Parse + Normalise ──► Load Previous Snapshot
                                                            │
                                                            ▼
                                                    Diff Against Snapshot
                                                            │
                                              ┌─────────────┴─────────────┐
                                              ▼                           ▼
                                     Append Changes              Upsert Snapshot
```

**Two decisions that separate a scraper that works from one that's cheap to run:**

1. **`Parse + Normalise` throws when the selector matches 0 items.** A page that
   silently stops matching returns an empty result. Appended to a sheet, that is
   indistinguishable from "nothing changed this week" — you'd never know your
   scraper was dead. Throwing makes the difference visible.
2. **The diff only emits new or changed rows.** Re-appending the full page every
   6 hours duplicates the sheet and burns API quota for zero new information.

Prices are coerced explicitly and flagged with `price_ok` rather than dropped,
so the row count always reconciles against the page.

### Schema for the Postgres node

```sql
CREATE TABLE scrape_snapshot (
  url          TEXT PRIMARY KEY,
  price        NUMERIC,
  availability TEXT,
  rating       NUMERIC,
  scraped_at   TIMESTAMPTZ
);
```

The `ON CONFLICT (url) DO UPDATE` makes a re-run idempotent — it cannot
duplicate rows, which is the failure mode that quietly poisons a data store.

> Target site is `books.toscrape.com`, a public sandbox built for scraping
> practice. In real client work, check `robots.txt` and the site's terms first,
> and decline anything that forbids it.

---

## Validating

```bash
python3 validate_workflows.py
```

Checks what actually breaks an import: required top-level keys, required node
fields, unique node ids, connection endpoints that point at real nodes, nodes
reachable from a trigger, and no credentialed node left enabled.

```
OK    01-form-intake-to-crm.json  (8 nodes, 3 credentialed/disabled)
OK    02-scheduled-scrape-to-sheet.json  (8 nodes, 3 credentialed/disabled)

all workflows valid
```

**This validator exists because the first version of workflow 1 could not be
imported at all.** The file it was built from was missing `connections` and
`typeVersion` on every node, and its Gmail node had a subject and recipient but
**no message body** — it would have sent empty emails. It also did not lowercase
emails, so `Ada@x.com` and `ada@x.com` were two CRM contacts. None of that
shows up if you only check that the JSON parses.

Run the validator against your own exports before shipping them to a client.
A file that parses is not a workflow that works.

---

## Enabling, in order

1. Import the workflow
2. Create the credential for the node
3. Fill in the placeholder id (sheet id, database)
4. Enable **one** node
5. Test that node
6. Move to the next

For workflow 2, enable `Load Previous Snapshot` first — the diff node reads from
it, so if it's off, every row looks new and the first run appends the whole page.
