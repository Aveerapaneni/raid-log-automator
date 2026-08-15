#!/usr/bin/env python3
"""US-7: Closed-entry retention for the RAID Log Automator.

Entries are never deleted, full stop — not just once Closed. Status can
be set to Closed (an allowed, ordinary field update), but removing an
entry from the dataset is always refused, with an explanation, regardless
of its status (Section 9). Closed entries stay present and queryable —
digest.py (US-6) and sprint_ready.py (US-8) already exclude them from
their *active* views, but neither of them, nor anything here, ever
removes an entry from the dataset itself.

Per Section 13 (US-9), closing an entry is persisted to raid_log.db so
it survives across separate process invocations, not just within one
run's in-memory copy.
"""

import argparse
import sys

import raid_data
import raid_db

CLOSED = "Closed"


class RetentionError(Exception):
    """Raised when an operation would remove or hard-delete an entry."""


def get_entry(entries, entry_id):
    for e in entries:
        if e["id"] == entry_id:
            return e
    raise KeyError(f"No entry with id {entry_id!r} in the dataset.")


def list_entries(entries, include_closed=True):
    if include_closed:
        return list(entries)
    return [e for e in entries if e.get("status") != CLOSED]


def close_entry(entries, entry_id):
    """Returns a new entries list with the given entry's Status set to
    Closed. This is the only way an entry's lifecycle "ends" — it is
    never removed, only marked Closed. Idempotent: closing an
    already-Closed entry is a harmless no-op."""
    get_entry(entries, entry_id)  # raises KeyError if missing
    return [dict(e, status=CLOSED) if e["id"] == entry_id else e for e in entries]


def remove_entry(entries, entry_id):
    """Always refuses. Entries are never deleted or hard-removed,
    regardless of Status — Closed included (Section 9)."""
    entry = get_entry(entries, entry_id)  # raises KeyError if missing
    raise RetentionError(
        f"Refusing to remove {entry_id!r} (Status: {entry.get('status')!r}). "
        "Entries are never deleted, even once Closed — set Status to "
        "'Closed' instead to retire it while keeping the historical record intact."
    )


def self_check(dataset, entries):
    notes = dataset.get("_schema_notes", {}).get("known_test_cases", {})
    expected_closed = set(notes.get("closed_entries_must_be_retained", []))
    if not expected_closed:
        return

    present_ids = {e["id"] for e in entries}
    print()
    print("Self-check against _schema_notes.known_test_cases:")
    all_passed = True

    if expected_closed <= present_ids:
        print(f"  OK   closed entries retained in dataset: {sorted(expected_closed)}")
    else:
        all_passed = False
        print(f"  FAIL missing closed entries: {sorted(expected_closed - present_ids)}")

    for eid in sorted(expected_closed):
        try:
            remove_entry(entries, eid)
            all_passed = False
            print(f"  FAIL removing {eid} was not refused")
        except RetentionError:
            print(f"  OK   removing {eid} was refused")

    print("All checks passed." if all_passed else "Some checks failed — see above.")


def main():
    parser = argparse.ArgumentParser(description="US-7: closed-entry retention.")
    parser.add_argument("--data", default="raid_mock_data.json", help="Path to the mock RAID dataset JSON")
    parser.add_argument("--db", default=raid_db.DEFAULT_DB_PATH, help="Path to the persistent SQLite store")
    parser.add_argument("--close", metavar="ID", help="Set an entry's Status to Closed (persisted)")
    parser.add_argument("--remove", metavar="ID", help="Attempt to remove an entry — always refused")
    args = parser.parse_args()

    dataset, entries = raid_data.load_converted_entries(args.data, args.db)

    if args.close:
        try:
            entries = close_entry(entries, args.close)
            raid_db.update_fields(args.db, args.close, status=CLOSED)
            print(f"{args.close}: Status set to Closed.")
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    exit_code = 0
    if args.remove:
        try:
            remove_entry(entries, args.remove)
        except RetentionError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            exit_code = 1
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    all_count = len(list_entries(entries, include_closed=True))
    open_count = len(list_entries(entries, include_closed=False))
    print(f"Total entries retained: {all_count} (Open: {open_count}, Closed: {all_count - open_count})")

    self_check(dataset, entries)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
