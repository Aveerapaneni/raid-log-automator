#!/usr/bin/env python3
"""US-4: Runtime-configurable escalation check for the RAID Log Automator.

Each run, the PM supplies a score-band threshold (Low/Medium/High) and a
days-open threshold. Any open, scorable entry whose Priority bucket meets
or exceeds the score-band AND whose Days Open meets or exceeds the
days-open threshold has its Status auto-updated to "Escalated". Each
escalation is appended to a timestamped, append-only log file.

Per Section 9: if no threshold is supplied (neither on the command line nor
interactively), the tool refuses to run the check rather than silently
defaulting.
"""

import argparse
import json
import sys
from datetime import date, datetime, timezone

import days_and_status as ds
import raid_data
import raid_store
import score_and_validate as sv

PRIORITY_RANK = {"Low": 1, "Medium": 2, "High": 3}
ESCALATED = "Escalated"
CLOSED = "Closed"


def build_records(entries, today=None):
    """Merge US-1 (priority) and US-3 (effective status/days open) output per entry."""
    score_by_id = {r["id"]: r for r in sv.process(entries)}
    status_by_id = {r["id"]: r for r in ds.process(entries, today=today)}
    records = []
    for e in entries:
        eid = e["id"]
        score = score_by_id[eid]
        status = status_by_id[eid]
        records.append(
            {
                "id": eid,
                "category": e["category"],
                "status": status["status"],
                "days_open": status["days_open"],
                "priority_score": score["priority_score"],
                "priority_bucket": score["priority_bucket"],
                "scorable": score["scorable"],
            }
        )
    return records


def breaches_threshold(record, score_band, days_open_threshold):
    """True if a record should escalate under the supplied thresholds."""
    if record["status"] in (CLOSED, ESCALATED):
        return False
    if not record["scorable"]:
        return False
    if PRIORITY_RANK[record["priority_bucket"]] < PRIORITY_RANK[score_band]:
        return False
    if record["days_open"] is None or record["days_open"] < days_open_threshold:
        return False
    return True


def apply_escalations(records, score_band, days_open_threshold, timestamp=None):
    """Returns (updated_records, events). Records are not mutated in place;
    breaching entries get a new dict with status='Escalated'. Idempotent:
    entries already 'Escalated' or 'Closed' never re-trigger (see
    breaches_threshold)."""
    if score_band not in PRIORITY_RANK:
        raise ValueError(f"score_band must be one of {list(PRIORITY_RANK)}, got {score_band!r}")
    if not isinstance(days_open_threshold, int) or days_open_threshold < 0:
        raise ValueError("days_open_threshold must be a non-negative integer")

    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    updated_records = []
    events = []
    for r in records:
        if breaches_threshold(r, score_band, days_open_threshold):
            events.append(
                {
                    "timestamp": timestamp,
                    "id": r["id"],
                    "category": r["category"],
                    "previous_status": r["status"],
                    "new_status": ESCALATED,
                    "priority_score": r["priority_score"],
                    "priority_bucket": r["priority_bucket"],
                    "days_open": r["days_open"],
                    "score_band_threshold": score_band,
                    "days_open_threshold": days_open_threshold,
                }
            )
            updated_records.append(dict(r, status=ESCALATED))
        else:
            updated_records.append(r)
    return updated_records, events


def resolve_score_band(value, prompt=input):
    """Section 9: refuse to run without a threshold rather than defaulting."""
    if value is None:
        value = prompt("Score-band threshold (Low/Medium/High): ").strip()
    if value not in PRIORITY_RANK:
        raise ValueError(f"Score-band threshold must be one of {list(PRIORITY_RANK)}, got {value!r}")
    return value


def resolve_days_open_threshold(value, prompt=input):
    if value is None:
        raw = prompt("Days-open threshold (integer, e.g. 30): ").strip()
        if not raw:
            raise ValueError("Days-open threshold is required — refusing to run the escalation check without one.")
        value = raw
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Days-open threshold must be an integer, got {value!r}")
    if value < 0:
        raise ValueError("Days-open threshold must be zero or a positive integer.")
    return value


def persist_escalations(db_path, events):
    """Writes back Status='Escalated' for each escalation event, so it
    survives to the next run (US-9) -- which is what makes the existing
    idempotency guard in breaches_threshold() (skip anything already
    Escalated) actually mean something across separate invocations,
    not just within one."""
    for event in events:
        raid_store.update_fields(db_path, event["id"], status=ESCALATED)


def append_log(events, log_path):
    if not events:
        return
    with open(log_path, "a") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def print_report(records, events, score_band, days_open_threshold):
    escalated = {e["id"]: e for e in events}
    print(f"Escalation check — score-band >= {score_band}, days-open >= {days_open_threshold}")
    print()
    header = f"{'ID':10} {'Category':11} {'Status':24} {'Bucket':7} {'Score':>5} {'Days Open':9}"
    print(header)
    print("-" * len(header))
    for r in records:
        if r["id"] in escalated:
            status_col = f"{escalated[r['id']]['previous_status']} -> Escalated"
        else:
            status_col = r["status"]
        bucket = r["priority_bucket"] or "-"
        score = r["priority_score"] if r["priority_score"] is not None else "-"
        days = r["days_open"] if r["days_open"] is not None else "-"
        print(f"{r['id']:10} {r['category']:11} {status_col:24} {bucket:7} {score!s:>5} {days!s:>9}")

    print()
    print(f"Escalated this run: {len(events)} -> {sorted(escalated)}")


def main():
    parser = argparse.ArgumentParser(description="US-4: runtime-configurable escalation check.")
    parser.add_argument("--data", default=None, help="Path to the mock RAID dataset seed (JSON or xlsx template)")
    parser.add_argument("--db", default=raid_store.DEFAULT_DB_PATH, help="Path to the persistent store (.db or .xlsx)")
    parser.add_argument("--score-band", dest="score_band", default=None, choices=list(PRIORITY_RANK))
    parser.add_argument("--days-open", dest="days_open", default=None, type=int)
    parser.add_argument("--today", default=None, help="Override 'today' as YYYY-MM-DD")
    parser.add_argument("--log", dest="log_path", default="escalation_log.jsonl")
    args = parser.parse_args()

    try:
        score_band = resolve_score_band(args.score_band)
        days_open_threshold = resolve_days_open_threshold(args.days_open)
    except ValueError as exc:
        print(f"Refusing to run escalation check: {exc}", file=sys.stderr)
        return 1

    today = ds.parse_date(args.today) if args.today else None
    seed_path = args.data or raid_store.default_seed_path(args.db)

    dataset, entries = raid_data.load_converted_entries(seed_path, args.db)

    records = build_records(entries, today=today)
    timestamp = datetime.now(timezone.utc).isoformat()
    updated_records, events = apply_escalations(records, score_band, days_open_threshold, timestamp=timestamp)

    print_report(records, events, score_band, days_open_threshold)
    persist_escalations(args.db, events)
    append_log(events, args.log_path)
    if events:
        print(f"\nLogged {len(events)} escalation(s) to {args.log_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
