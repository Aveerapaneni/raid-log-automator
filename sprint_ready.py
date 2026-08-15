#!/usr/bin/env python3
"""US-8: Sprint Ready pile for the RAID Log Automator.

An entry qualifies if it's valid per US-2 (Owner present, Mitigation Plan
present where required, Probability present where required, Impact
present, all in range), has a Start Date, has no active Blocked flag, and
its (US-3 effective) Status is not Closed.

Ordering: unscored eligible entries (blank-Probability Issues, valid per
US-2 but unscored per Section 9) sit at the very top, ordered among
themselves by Date Raised -- a live, active Issue takes precedence over
any scored item. Scored entries follow, ordered by Priority bucket
(High -> Medium -> Low), ties broken by Date Raised. A true tie -- same
tier/bucket AND same Date Raised, meaning the two orderings keys can't
distinguish them -- is flagged explicitly for the PM rather than silently
resolved by insertion order (Section 9).
"""

import argparse
import sys
from collections import Counter

import days_and_status as ds
import raid_data
import raid_store
import score_and_validate as sv

CLOSED = "Closed"
BUCKET_RANK = {"Low": 1, "Medium": 2, "High": 3}


def build_pile_candidates(entries, today=None):
    """Merge US-1 (priority/validity) and US-3 (effective status) per entry."""
    score_by_id = {r["id"]: r for r in sv.process(entries)}
    status_by_id = {r["id"]: r for r in ds.process(entries, today=today)}
    candidates = []
    for e in entries:
        eid = e["id"]
        score = score_by_id[eid]
        status = status_by_id[eid]
        candidates.append(
            {
                "id": eid,
                "category": e["category"],
                "date_raised": e.get("date_raised"),
                "start_date": e.get("start_date"),
                "blocked_by": e.get("blocked_by") or [],
                "status": status["status"],
                "is_valid": score["is_valid"],
                "scorable": score["scorable"],
                "priority_score": score["priority_score"],
                "priority_bucket": score["priority_bucket"],
            }
        )
    return candidates


def is_eligible(candidate):
    if not candidate["is_valid"]:
        return False
    if not candidate["start_date"]:
        return False
    if candidate["blocked_by"]:
        return False
    if candidate["status"] == CLOSED:
        return False
    return True


def sort_key(candidate):
    """Unscored tier (0) sorts entirely ahead of the scored tier (1).
    Within scored, higher bucket rank sorts first; within each tier,
    earlier Date Raised sorts first."""
    if candidate["scorable"]:
        return (1, -BUCKET_RANK[candidate["priority_bucket"]], candidate["date_raised"])
    return (0, 0, candidate["date_raised"])


def tie_key(candidate):
    """Two candidates with an identical tie_key are indistinguishable by
    the ordering rule -- a true tie, per Section 9."""
    if candidate["scorable"]:
        return ("scored", candidate["priority_bucket"], candidate["date_raised"])
    return ("unscored", candidate["date_raised"])


def build_pile(entries, today=None):
    candidates = build_pile_candidates(entries, today=today)
    eligible = [c for c in candidates if is_eligible(c)]
    ordered = sorted(eligible, key=sort_key)

    key_counts = Counter(tie_key(c) for c in ordered)
    for c in ordered:
        c["is_tie"] = key_counts[tie_key(c)] > 1

    return ordered


def print_report(pile):
    if not pile:
        print("Sprint Ready pile is empty — no entries currently qualify.")
        return

    header = f"{'#':3} {'ID':10} {'Category':11} {'Tier':9} {'Bucket':7} {'Date Raised':12} {'Tie?':4}"
    print(header)
    print("-" * len(header))
    for i, c in enumerate(pile, start=1):
        tier = "unscored" if not c["scorable"] else "scored"
        bucket = c["priority_bucket"] or "-"
        tie = "TIE" if c["is_tie"] else "-"
        print(f"{i:3} {c['id']:10} {c['category']:11} {tier:9} {bucket:7} {c['date_raised']:12} {tie:4}")

    ties = sorted({c["id"] for c in pile if c["is_tie"]})
    print()
    print(f"Total Sprint Ready: {len(pile)}")
    if ties:
        print(f"True ties flagged for PM attention: {ties}")


def self_check(dataset, pile):
    notes = dataset.get("_schema_notes", {}).get("known_test_cases", {})
    if not notes:
        return

    pile_ids = {c["id"] for c in pile}
    tied_ids = {c["id"] for c in pile if c["is_tie"]}

    print()
    print("Self-check against _schema_notes.known_test_cases:")
    all_passed = True

    expected_excluded = set(notes.get("blocked_excluded_from_sprint_ready", []))
    if expected_excluded.isdisjoint(pile_ids):
        print(f"  OK   blocked entries excluded from pile: {sorted(expected_excluded)}")
    else:
        all_passed = False
        print(f"  FAIL these blocked entries leaked into the pile: {sorted(expected_excluded & pile_ids)}")

    expected_closed_excluded = set(notes.get("closed_entries_must_be_retained", []))
    if expected_closed_excluded.isdisjoint(pile_ids):
        print(f"  OK   closed entries excluded from pile: {sorted(expected_closed_excluded)}")
    else:
        all_passed = False
        print(f"  FAIL these closed entries leaked into the pile: {sorted(expected_closed_excluded & pile_ids)}")

    expected_tie = set(notes.get("true_tie_priority_and_date_raised", []))
    if expected_tie and expected_tie <= tied_ids:
        print(f"  OK   true tie flagged: {sorted(expected_tie)}")
    else:
        all_passed = False
        print(f"  FAIL expected tie {sorted(expected_tie)}, got tied ids {sorted(tied_ids)}")

    print("All checks passed." if all_passed else "Some checks failed — see above.")


def main():
    parser = argparse.ArgumentParser(description="US-8: build the Sprint Ready pile.")
    parser.add_argument("--data", default=None, help="Path to the mock RAID dataset seed (JSON or xlsx template)")
    parser.add_argument("--db", default=raid_store.DEFAULT_DB_PATH, help="Path to the persistent store (.db or .xlsx)")
    parser.add_argument("--today", default=None, help="Override 'today' as YYYY-MM-DD")
    args = parser.parse_args()

    today = ds.parse_date(args.today) if args.today else None
    seed_path = args.data or raid_store.default_seed_path(args.db)

    dataset, entries = raid_data.load_converted_entries(seed_path, args.db)

    pile = build_pile(entries, today=today)
    print_report(pile)
    self_check(dataset, pile)
    return 0


if __name__ == "__main__":
    sys.exit(main())
