#!/usr/bin/env python3
"""US-3: Days Open and Status auto-transition for the RAID Log Automator.

Given the mock dataset, computes:
  - Days Open = today - Date Raised, blank (None) whenever Status is Closed.
  - Status auto-transitions from "Not Started" to "In Progress" the moment
    Start Date is set. This is a one-way promotion out of "Not Started" only
    -- Monitoring/Escalated/Closed are left as-is even if Start Date is set,
    since those reflect later-stage handling this story doesn't own
    (Escalated is US-4; Closed is a PM decision).

Per Section 13 (US-9), a Status promotion is persisted to raid_log.db so
it survives across separate process invocations, not just within one
run's in-memory copy.
"""

import argparse
import json
import sys
from datetime import date, datetime

import materialize_conversion as mc
import raid_db

NOT_STARTED = "Not Started"
IN_PROGRESS = "In Progress"
CLOSED = "Closed"


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def compute_status(entry):
    """Returns (new_status, changed). Promotes Not Started -> In Progress
    the moment Start Date is set; leaves every other status untouched."""
    current = entry.get("status")
    if current == NOT_STARTED and entry.get("start_date"):
        return IN_PROGRESS, True
    return current, False


def compute_days_open(entry, effective_status, today=None):
    """Days Open = today - Date Raised, blank once Status is Closed."""
    if effective_status == CLOSED:
        return None
    today = today or date.today()
    date_raised = parse_date(entry["date_raised"])
    return (today - date_raised).days


def process(entries, today=None):
    results = []
    for entry in entries:
        new_status, changed = compute_status(entry)
        days_open = compute_days_open(entry, new_status, today=today)
        results.append(
            {
                "id": entry["id"],
                "category": entry["category"],
                "date_raised": entry.get("date_raised"),
                "start_date": entry.get("start_date"),
                "original_status": entry.get("status"),
                "status": new_status,
                "status_changed": changed,
                "days_open": days_open,
            }
        )
    return results


def persist_status_promotions(db_path, results):
    """Writes back any Status promotion (Not Started -> In Progress), so
    it survives to the next run (US-9)."""
    for r in results:
        if r["status_changed"]:
            raid_db.update_fields(db_path, r["id"], status=r["status"])


def load_and_process(db_path, seed_path, today=None):
    """Loads live entries from the database (auto-seeding from
    seed_path if needed), applies the US-5 conversion in-memory for
    consistent Category display and persists any new conversions,
    computes Days Open / Status for *this* run, and persists any new
    Status promotions. Returns (dataset, results)."""
    raid_db.ensure_db(db_path, seed_path)
    with open(seed_path) as f:
        dataset = json.load(f)
    entries = raid_db.load_entries(db_path)
    converted, conversion_events = mc.process(entries)
    mc.persist_conversions(db_path, conversion_events)

    results = process(converted, today=today)
    persist_status_promotions(db_path, results)
    return dataset, results


def print_report(results):
    header = f"{'ID':10} {'Category':11} {'Date Raised':12} {'Start Date':12} {'Status':22} {'Days Open':9}"
    print(header)
    print("-" * len(header))
    for r in results:
        status_col = r["status"]
        if r["status_changed"]:
            status_col = f"{r['original_status']} -> {r['status']}"
        start = r["start_date"] or "-"
        days = r["days_open"] if r["days_open"] is not None else "-"
        print(f"{r['id']:10} {r['category']:11} {r['date_raised']:12} {start:12} {status_col:22} {days!s:>9}")

    changed = [r for r in results if r["status_changed"]]
    blank_days = [r for r in results if r["days_open"] is None]
    print()
    print(f"Total entries: {len(results)}")
    print(f"Status auto-promoted to In Progress: {len(changed)} -> {[r['id'] for r in changed]}")
    print(f"Days Open blank (Closed): {len(blank_days)} -> {[r['id'] for r in blank_days]}")


def self_check(dataset, results):
    notes = dataset.get("_schema_notes", {}).get("known_test_cases", {})
    if not notes:
        return

    by_id = {r["id"]: r for r in results}

    print()
    print("Self-check against _schema_notes.known_test_cases:")
    all_passed = True

    # Checks final Status, not status_changed: once persisted (US-9), a
    # promotion detected on an earlier run correctly shows
    # status_changed=False on this run -- it already happened. What must
    # hold regardless of which run did the promoting is that these
    # entries end up "In Progress".
    expected_promoted = set(notes.get("start_date_set_but_status_not_updated", []))
    actually_in_progress = {r["id"] for r in results if r["status"] == IN_PROGRESS}
    if expected_promoted <= actually_in_progress:
        print(f"  OK   start_date_set_but_status_not_updated is now In Progress: {sorted(expected_promoted)}")
    else:
        all_passed = False
        missed = expected_promoted - actually_in_progress
        print(f"  FAIL expected these to be In Progress but weren't: {sorted(missed)}")

    expected_blank = set(notes.get("closed_entries_must_be_retained", []))
    actual_blank = {r["id"] for r in results if r["days_open"] is None}
    if expected_blank <= actual_blank:
        print(f"  OK   closed entries have blank Days Open: {sorted(expected_blank)}")
    else:
        all_passed = False
        missed = expected_blank - actual_blank
        print(f"  FAIL expected these to have blank Days Open but didn't: {sorted(missed)}")

    print("All checks passed." if all_passed else "Some checks failed — see above.")


def main():
    parser = argparse.ArgumentParser(description="US-3: Days Open and Status auto-transition.")
    parser.add_argument("--data", default="raid_mock_data.json", help="Path to the mock RAID dataset JSON")
    parser.add_argument("--db", default=raid_db.DEFAULT_DB_PATH, help="Path to the persistent SQLite store")
    parser.add_argument("--today", default=None, help="Override 'today' as YYYY-MM-DD (defaults to the real current date)")
    args = parser.parse_args()

    today = parse_date(args.today) if args.today else None

    dataset, results = load_and_process(args.db, args.data, today=today)
    print_report(results)
    self_check(dataset, results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
