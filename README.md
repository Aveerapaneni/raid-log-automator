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

Eight user stories, each implemented as its own small, independently
runnable Python module with a pure-function core and a pytest suite:

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

`raid_tool.py` is the single entry point that wires all eight together as
subcommands, plus a `report` command that runs the full end-to-end picture in
one shot. `raid_data.py` is a small shared helper that every module's
`main()` uses to load the dataset and apply the US-5 conversion before doing
its own work, so a materialized Risk is treated as an Issue consistently
everywhere — not just when `materialize_conversion.py` happens to be the
script that ran.

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
`pytest` (for the test suite).

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

### Tests

```bash
python3 -m pytest
```

170 tests across 8 test files, covering the pure logic functions directly
(not just the CLI output) — boundary values, invalid ranges, idempotency,
and every documented edge case from PRD Section 9.

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
