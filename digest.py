#!/usr/bin/env python3
"""US-6: Manually-triggered digest for the RAID Log Automator.

Selects the top N (3-5, PM-configurable) highest-priority OPEN items
(Closed items excluded, per Section 6) and presents them grouped by
category in plain text a non-technical stakeholder can read without
touching any code. Per Section 4.2, no AI/API call happens here -- if
the PM wants an AI-written narrative layered on top, that's a separate,
human-driven Claude Code session using this digest's output as input.
This only runs when explicitly invoked -- there is no scheduler in v1.

Ranking mirrors the Sprint Ready precedent (US-8, Section 9): an
unscored-but-valid open item (a blank-Probability Issue) ranks ahead of
every scored item, ordered by Date Raised among themselves, since a
live, active problem shouldn't be buried by items that merely scored
higher.
"""

import argparse
import sys
from collections import defaultdict

import days_and_status as ds
import raid_data
import raid_db
import score_and_validate as sv

CLOSED = "Closed"
CATEGORY_ORDER = ["Risk", "Assumption", "Issue", "Dependency"]


def build_digest_candidates(entries, today=None):
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
                "description": e.get("description"),
                "owner": e.get("owner"),
                "status": status["status"],
                "days_open": status["days_open"],
                "scorable": score["scorable"],
                "is_valid": score["is_valid"],
                "priority_score": score["priority_score"],
                "priority_bucket": score["priority_bucket"],
                "date_raised": e.get("date_raised"),
            }
        )
    return candidates


def is_open(candidate):
    return candidate["status"] != CLOSED


def is_digest_eligible(candidate):
    """Open, and either has a computable Priority or is the one sanctioned
    unscored case: a valid Issue with blank Probability. An entry that's
    unscored *because it's invalid* (e.g. missing Probability on a
    non-Issue) has no principled way to be ranked "highest-priority" and
    is excluded rather than given the same top billing as a genuinely
    live, valid item (Section 9: invalid entries are excluded from
    scoring until corrected, not promoted)."""
    if not is_open(candidate):
        return False
    if not candidate["scorable"] and not candidate["is_valid"]:
        return False
    return True


def sort_key(candidate):
    if candidate["scorable"]:
        return (1, -candidate["priority_score"], candidate["date_raised"])
    return (0, 0, candidate["date_raised"])


def select_top_items(entries, count=5, today=None):
    if not 3 <= count <= 5:
        raise ValueError("count must be between 3 and 5, per US-6's 'top 3-5' scope")
    candidates = build_digest_candidates(entries, today=today)
    eligible = [c for c in candidates if is_digest_eligible(c)]
    ordered = sorted(eligible, key=sort_key)
    return ordered[:count]


def group_by_category(items):
    grouped = defaultdict(list)
    for item in items:
        grouped[item["category"]].append(item)
    return grouped


def format_item(item):
    if item["priority_bucket"]:
        priority_label = f"{item['priority_bucket']} ({item['priority_score']})"
    else:
        priority_label = "Unscored — live item, no Probability yet"
    days_open = item["days_open"] if item["days_open"] is not None else "-"
    owner = item["owner"] or "(no owner assigned)"
    return (
        f"  [{item['id']}] {item['description']}\n"
        f"      Owner: {owner} | Priority: {priority_label} | Days Open: {days_open} | Status: {item['status']}"
    )


def format_digest(items, today_label):
    lines = [f"RAID Log Digest — top {len(items)} highest-priority open items as of {today_label}", "=" * 70]
    if not items:
        lines.append("No open items currently qualify for the digest.")
        return "\n".join(lines)

    grouped = group_by_category(items)
    for category in CATEGORY_ORDER:
        if category not in grouped:
            continue
        lines.append("")
        lines.append(category.upper())
        lines.append("-" * len(category))
        for item in grouped[category]:
            lines.append(format_item(item))
    return "\n".join(lines)


def self_check(dataset, items):
    notes = dataset.get("_schema_notes", {}).get("known_test_cases", {})
    if not notes:
        return

    item_ids = {i["id"] for i in items}

    print()
    print("Self-check against _schema_notes.known_test_cases:")
    all_passed = True

    invalid_unscored = set(notes.get("missing_probability", []))
    if invalid_unscored.isdisjoint(item_ids):
        print(f"  OK   invalid unscored entries excluded from digest: {sorted(invalid_unscored)}")
    else:
        all_passed = False
        print(f"  FAIL these invalid unscored entries leaked into the digest: {sorted(invalid_unscored & item_ids)}")

    valid_unscored = set(notes.get("valid_blank_probability_issue_only", []))
    if valid_unscored <= item_ids:
        print(f"  OK   valid unscored Issue included and ranked first: {sorted(valid_unscored)}")
    else:
        all_passed = False
        print(f"  FAIL expected {sorted(valid_unscored)} in digest, got {sorted(item_ids)}")

    print("All checks passed." if all_passed else "Some checks failed — see above.")


def main():
    parser = argparse.ArgumentParser(description="US-6: manually-triggered RAID digest.")
    parser.add_argument("--data", default="raid_mock_data.json", help="Path to the mock RAID dataset JSON")
    parser.add_argument("--db", default=raid_db.DEFAULT_DB_PATH, help="Path to the persistent SQLite store")
    parser.add_argument("--count", type=int, default=5, choices=[3, 4, 5], help="How many top items to include (3-5)")
    parser.add_argument("--today", default=None, help="Override 'today' as YYYY-MM-DD")
    args = parser.parse_args()

    today = ds.parse_date(args.today) if args.today else None

    dataset, entries = raid_data.load_converted_entries(args.data, args.db)

    items = select_top_items(entries, count=args.count, today=today)
    today_label = args.today or "today"
    print(format_digest(items, today_label))
    self_check(dataset, items)
    return 0


if __name__ == "__main__":
    sys.exit(main())
