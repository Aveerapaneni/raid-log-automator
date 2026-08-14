#!/usr/bin/env python3
"""US-5: Materialized-Risk -> Issue auto-conversion for the RAID Log Automator.

When a Risk entry's Materialized flag is true, its Category updates to
Issue in place -- same ID, all other fields (including the Materialized
flag itself) preserved as history. Idempotent by construction: once an
entry's Category is Issue, it no longer matches a Risk and is left alone
on any later run, so re-processing never creates a duplicate or re-fires
the conversion (Section 9).
"""

import argparse
import json
import sys

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


def print_report(events):
    print(f"Materialized-Risk conversions this run: {len(events)}")
    for e in events:
        print(f"  {e['id']}: {e['previous_category']} -> {e['new_category']}")
    if not events:
        print("  (none)")


def self_check(dataset, events):
    notes = dataset.get("_schema_notes", {}).get("known_test_cases", {})
    expected = set(notes.get("materialized_risk_should_convert_to_issue", []))
    if not expected:
        return
    actual = {e["id"] for e in events}
    print()
    print("Self-check against _schema_notes.known_test_cases:")
    if expected == actual:
        print(f"  OK   materialized_risk_should_convert_to_issue: {sorted(expected)}")
    else:
        print(f"  FAIL expected {sorted(expected)}, got {sorted(actual)}")


def main():
    parser = argparse.ArgumentParser(description="US-5: convert materialized Risks to Issues.")
    parser.add_argument("--data", default="raid_mock_data.json", help="Path to the mock RAID dataset JSON")
    args = parser.parse_args()

    with open(args.data) as f:
        dataset = json.load(f)

    updated, events = process(dataset["entries"])
    print_report(events)
    self_check(dataset, events)
    return 0


if __name__ == "__main__":
    sys.exit(main())
