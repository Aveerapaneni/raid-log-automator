# RAID Log Automator

Automating RAID log management for better planning and roadmap transparency.

## Problem

Risks, Assumptions, Issues, and Dependencies are usually tracked manually in a
spreadsheet, reviewed inconsistently, and rely on a Program Manager
remembering to enforce discipline — naming an owner, requiring a mitigation
plan, converting a materialized risk into an issue, escalating aging items.

This project automates the mechanical, rule-based parts of maintaining a RAID
log — scoring, validation, aging, escalation, category discipline, and
readiness queuing — using mock data, while the PM and stakeholders remain the
decision-makers on what actually gets done about each item.

Full requirements: [`raid-log-automator-PRD.md`](raid-log-automator-PRD.md).

## Approach

v1's eight user stories, each implemented as its own small, independently
runnable Python module with a pure-function core and a pytest suite, plus
US-9 (the first scoped piece of v2 — see PRD Section 13):

| Story | Module | What it does |
|---|---|---|
| US-1 | `score_and_validate.py` | Priority = Probability × Impact, bucketed Low/Medium/High |
| US-2 | `score_and_validate.py` | Flags entries missing Owner, Mitigation Plan, or Probability per category rules |
| US-3 | `days_and_status.py` | Days Open from Date Raised (blank once Closed); auto-promotes Status to "In Progress" |
| US-4 | `escalation.py` | Runtime-configurable score-band + days-open escalation, with a timestamped audit log |
| US-5 | `materialize_conversion.py` | Materialized Risk → Issue, in place, idempotent |
| US-6 | `digest.py` | Manually-triggered top 3-5 highest-priority open items, grouped by category |
| US-7 | `retention.py` | Entries are never deleted — closing is the only allowed lifecycle transition |
| US-8 | `sprint_ready.py` | Prioritized, unblocked-only "Sprint Ready" queue |
| US-9 | `raid_db.py` | Local SQLite persistence — state changes survive across separate runs |

`raid_tool.py` is the single entry point that wires all of them together as
subcommands, plus a `report` command that runs the full end-to-end picture in
one shot. `raid_data.py` is a small shared helper most modules' `main()`
uses to load current entries from the database (auto-seeding it from the
JSON on first use) with the two automatic, rule-based transitions — the US-5
conversion and the US-3 Status promotion — already applied and persisted, so
a materialized Risk reads as an Issue, and a started item reads as "In
Progress," consistently everywhere, regardless of which command happened to
trigger the transition first.

Nothing in this project calls out to a live AI/API at runtime. Any
AI-assisted text (e.g. writing a narrative on top of the digest's structured
output) is something the PM asks Claude Code to do directly in an
interactive session — a human-driven step, not code that calls an API on its
own.

## Design decisions

These came out of planning and constrain the whole project (see PRD
Section 4 for the full writeup):

- **Data independence.** `raid_mock_data.json` is its own dataset, created
  independently — no shared file or code dependency with the
  [Sprint Planning Automator](https://github.com/Aveerapaneni/sprint-planning-automator)
  repo. Each project runs standalone.
- **No cost beyond Claude Pro.** Everything here runs with zero dependency on
  a paid Anthropic API key. No autonomous API calls happen at runtime —
  verified by running the whole suite with no API key configured.
- **"Sprint Ready pile" is a shared name, not a shared dependency.** US-8
  borrows the term from the Sprint Planning Automator project because the
  concept (a prioritized, groomed queue) is genuinely analogous — but the
  implementation here is entirely self-contained.

## Running it

No API key, no external services, no network calls. Just Python 3 and
`pytest` (for the test suite) — `sqlite3` is part of the standard library,
so persistence needs no extra install either.

```bash
# The full end-to-end picture in one command
python3 raid_tool.py report --today 2026-08-14

# Or run any single story on its own
python3 raid_tool.py score
python3 raid_tool.py status --today 2026-08-14
python3 raid_tool.py escalate --score-band High --days-open 60
python3 raid_tool.py materialize
python3 raid_tool.py digest --count 5
python3 raid_tool.py sprint-ready --today 2026-08-14
python3 raid_tool.py retain --close RAID-001
python3 raid_tool.py retain --remove RAID-008   # always refused, by design

# Each module also runs standalone, e.g.:
python3 score_and_validate.py
```

`--today` overrides "today" for date math (defaults to the real current
date) — useful for reproducible demo runs. Every command except `escalate`
(whose threshold is runtime-supplied, so there's no fixed expected outcome)
also prints a self-check against a set of known test cases baked into
`raid_mock_data.json`'s `_schema_notes`, so you can see at a glance whether
the deliberately-planted edge cases (missing owners, blocked items, a
materialized risk, a true priority tie, etc.) are being handled correctly.

### Persistence (US-9)

The first command you run creates `raid_log.db` (gitignored — it's local,
per-machine runtime state, not something to commit) and seeds it from
`raid_mock_data.json`. `raid_mock_data.json` itself is never written to; it
stays the canonical, portable mock dataset. From then on, every command
reads and writes that database, so a status promotion, an escalation, a
materialized-Risk conversion, or a close survives across separate runs —
run `escalate` twice with the same thresholds and the second run correctly
reports zero *new* escalations, since the first run's result already stuck.
Point `--db` at a different path to run against an isolated copy (useful for
demos — see `test_persistence_integration.py` for exactly this pattern).
There's currently no way to reset the database back to the seed short of
deleting the `.db` file by hand — that's `reset-db`, US-10, not yet built.

### Tests

```bash
python3 -m pytest
```

202 tests across 10 test files, covering the pure logic functions directly
(not just the CLI output) — boundary values, invalid ranges, idempotency,
and every documented edge case from PRD Section 9. `test_persistence_integration.py`
goes a step further for US-9: it shells out to `raid_tool.py` via
`subprocess` so the idempotency guarantee is proven across genuinely
separate process invocations, not just two calls within one Python process.

## Data

`raid_mock_data.json` — 27 mock RAID entries across all four categories,
deliberately including incomplete ones (missing Owner, missing Mitigation
Plan, missing Probability), a materialized Risk, blocked and Closed entries,
and a genuine Priority + Date Raised tie — so the validation, escalation, and
ordering logic has real cases to catch. See the `_schema_notes` key at the
top of the file for what each planted case is testing.

## Related project

[Sprint Planning Automator](https://github.com/Aveerapaneni/sprint-planning-automator) —
a separate, independent portfolio project automating sprint planning. Linked
here for context only; there is no code or data dependency between the two.
