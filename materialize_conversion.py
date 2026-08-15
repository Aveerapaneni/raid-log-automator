#!/usr/bin/env python3
"""US-5: Materialized-Risk -> Issue auto-conversion for the RAID Log Automator.

When a Risk entry's Materialized flag is true, its Category updates to
Issue in place -- same ID, all other fields (including the Materialized
flag itself) preserved as history. Idempotent by construction: once an
entry's Category is Issue, it no longer matches a Risk and is left alone
on any later run, so re-processing never creates a duplicate or re-fires
the conversion (Section 9).

Per Section 13 (US-9), a converted Category is persisted to raid_log.db
so the conversion survives across separate process invocations, not just
within one run's in-memory copy.
"""

import argparse
import json
import sys

import raid_store

RISK = "Risk"
ISSUE = "Issue"


def is_materialized_risk(entry):
    return entry.get("category") == RISK and entry.get("materialized") is True


def convert_entry(entry):
    """Returns (new_entry, converted). new_entry is a shallow copy with
    Category updated to Issue when the entry is a materialized Risk;
    otherwise the original entry is returned untouched (same object)."""
    if is_materialized_risk(entry):
        return dict(entry, category=ISSUE), True
    return entry, False


def process(entries):
    updated = []
    events = []
    for entry in entries:
        new_entry, converted = convert_entry(entry)
        updated.append(new_entry)
        if converted:
            events.append(
                {
                    "id": entry["id"],
                    "previous_category": entry["category"],
                    "new_category": new_entry["category"],
                }
            )
    return updated, events


def persist_conversions(db_path, events):
    """Writes back the Category update for each conversion event, so it
    survives to the next run (US-9)."""
    for event in events:
        raid_store.update_fields(db_path, event["id"], category=event["new_category"])


def load_and_convert(db_path, seed_path):
    """Loads live entries from the database (auto-seeding from
    seed_path if needed), applies the conversion, persists any new
    conversions, and returns (dataset, converted_entries, events) --
    `events` reflects only what changed in *this* call, which is what a
    caller reporting "conversions this run" needs (unlike the shared
    raid_data.load_converted_entries(), which just wants current
    entries and doesn't care what changed when)."""
    raid_store.ensure_db(db_path, seed_path)
    dataset = {} if raid_store.is_xlsx(seed_path) else json.load(open(seed_path))
    entries = raid_store.load_entries(db_path)
    updated, events = process(entries)
    persist_conversions(db_path, events)
    return dataset, updated, events


def print_report(events):
    print(f"Materialized-Risk conversions this run: {len(events)}")
    for e in events:
        print(f"  {e['id']}: {e['previous_category']} -> {e['new_category']}")
    if not events:
        print("  (none)")


def self_check(dataset, entries, events):
    """Checks final Category, not `events`: once persisted (US-9), a
    conversion detected on an earlier run correctly produces zero events
    on this run -- it already happened. What must hold regardless of
    which run did the converting is that these entries end up "Issue"."""
    notes = dataset.get("_schema_notes", {}).get("known_test_cases", {})
    expected = set(notes.get("materialized_risk_should_convert_to_issue", []))
    if not expected:
        return
    now_issue = {e["id"] for e in entries if e["category"] == ISSUE}
    print()
    print("Self-check against _schema_notes.known_test_cases:")
    if expected <= now_issue:
        print(f"  OK   materialized_risk_should_convert_to_issue (now Issue): {sorted(expected)}")
    else:
        print(f"  FAIL expected {sorted(expected)} to be Issue, missing: {sorted(expected - now_issue)}")


def main():
    parser = argparse.ArgumentParser(description="US-5: convert materialized Risks to Issues.")
    parser.add_argument("--data", default=None, help="Path to the mock RAID dataset seed (JSON or xlsx template)")
    parser.add_argument("--db", default=raid_store.DEFAULT_DB_PATH, help="Path to the persistent store (.db or .xlsx)")
    args = parser.parse_args()

    seed_path = args.data or raid_store.default_seed_path(args.db)
    dataset, updated, events = load_and_convert(args.db, seed_path)
    print_report(events)
    self_check(dataset, updated, events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
