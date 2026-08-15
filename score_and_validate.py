#!/usr/bin/env python3
"""US-1 (Priority scoring) and US-2 (log discipline validation) for the RAID Log Automator.

Reads raid_mock_data.json and, per entry, computes:
  - Priority score/bucket (US-1), when the entry has both Probability and Impact
    in range 1-5.
  - Validation flags (US-2): missing Owner, missing Mitigation Plan on a Risk/Issue,
    missing Probability on a non-Issue, missing/invalid Impact.

Validity (US-2) and scorability (US-1) are tracked separately: an Issue with a
blank Probability is valid but unscored (PRD Section 9).
"""

import argparse
import sys

import raid_data
import raid_store

MITIGATION_REQUIRED_CATEGORIES = {"Risk", "Issue"}
PROBABILITY_OPTIONAL_CATEGORY = "Issue"
TEAM_OWNER_KEYWORDS = ("team", "group", "dept", "department", "squad", "org")


def in_range(value):
    return isinstance(value, int) and 1 <= value <= 5


def looks_like_a_team(owner):
    if not owner:
        return False
    lowered = owner.lower()
    return any(keyword in lowered for keyword in TEAM_OWNER_KEYWORDS)


def compute_priority(entry):
    """US-1: Priority = Probability x Impact, bucketed Low(<8)/Medium(8-14)/High(15+).

    Returns (score, bucket, scorable, reason). reason explains why an entry
    wasn't scored when scorable is False.
    """
    impact = entry.get("impact")
    probability = entry.get("probability")

    if not in_range(impact):
        return None, None, False, "missing_or_invalid_impact"

    if probability is None:
        if entry.get("category") == PROBABILITY_OPTIONAL_CATEGORY:
            return None, None, False, "blank_probability_valid_issue"
        return None, None, False, "missing_probability_invalid"

    if not in_range(probability):
        return None, None, False, "invalid_probability"

    score = probability * impact
    if score < 8:
        bucket = "Low"
    elif score <= 14:
        bucket = "Medium"
    else:
        bucket = "High"
    return score, bucket, True, None


def validate_entry(entry):
    """US-2: log discipline rules. Returns (flags, warnings).

    flags are the hard rules from the US-2 acceptance criteria (+ the Section 9
    missing/invalid Impact edge case). warnings are softer schema notes (e.g. an
    Owner that reads like a team name) that don't block validity on their own.
    """
    flags = []
    warnings = []

    owner = entry.get("owner")
    if not owner:
        flags.append("missing_owner")
    elif looks_like_a_team(owner):
        warnings.append("owner_is_likely_team")

    category = entry.get("category")
    if category in MITIGATION_REQUIRED_CATEGORIES and not entry.get("mitigation_plan"):
        flags.append("missing_mitigation_plan")

    probability = entry.get("probability")
    if probability is None:
        if category != PROBABILITY_OPTIONAL_CATEGORY:
            flags.append("missing_probability")
    elif not in_range(probability):
        flags.append("invalid_probability")

    impact = entry.get("impact")
    if impact is None:
        flags.append("missing_impact")
    elif not in_range(impact):
        flags.append("invalid_impact")

    return flags, warnings


def process(entries):
    results = []
    for entry in entries:
        score, bucket, scorable, reason = compute_priority(entry)
        flags, warnings = validate_entry(entry)
        results.append(
            {
                "id": entry["id"],
                "category": entry["category"],
                "owner": entry.get("owner"),
                "priority_score": score,
                "priority_bucket": bucket,
                "scorable": scorable,
                "unscored_reason": reason,
                "is_valid": len(flags) == 0,
                "flags": flags,
                "warnings": warnings,
            }
        )
    return results


def print_report(results):
    header = f"{'ID':10} {'Category':11} {'Owner':18} {'Score':>5} {'Bucket':7} {'Valid':6} Flags / Warnings"
    print(header)
    print("-" * len(header))
    for r in results:
        owner = r["owner"] or "(missing)"
        score = r["priority_score"] if r["priority_score"] is not None else "-"
        bucket = r["priority_bucket"] or ("unscored" if not r["scorable"] else "-")
        valid = "yes" if r["is_valid"] else "NO"
        notes = ", ".join(r["flags"] + [f"[{w}]" for w in r["warnings"]])
        print(f"{r['id']:10} {r['category']:11} {owner:18} {score!s:>5} {bucket:7} {valid:6} {notes}")

    total = len(results)
    invalid = [r for r in results if not r["is_valid"]]
    unscored = [r for r in results if not r["scorable"]]
    bucket_counts = {"High": 0, "Medium": 0, "Low": 0}
    for r in results:
        if r["priority_bucket"]:
            bucket_counts[r["priority_bucket"]] += 1

    print()
    print(f"Total entries: {total}")
    print(f"Valid: {total - len(invalid)}   Flagged invalid: {len(invalid)}")
    print(f"Scored: {total - len(unscored)}   Unscored: {len(unscored)}")
    print(f"Buckets — High: {bucket_counts['High']}  Medium: {bucket_counts['Medium']}  Low: {bucket_counts['Low']}")


def self_check(entries, results):
    """Cross-check output against the dataset's own known_test_cases notes."""
    notes = entries.get("_schema_notes", {}).get("known_test_cases", {})
    if not notes:
        return

    by_id = {r["id"]: r for r in results}

    checks = [
        ("missing_owner", "missing_owner", lambda r: "missing_owner" in r["flags"]),
        ("owner_is_a_team_not_a_person", "owner_is_likely_team", lambda r: "owner_is_likely_team" in r["warnings"]),
        ("missing_mitigation_plan", "missing_mitigation_plan", lambda r: "missing_mitigation_plan" in r["flags"]),
        ("missing_probability", "missing_probability", lambda r: "missing_probability" in r["flags"]),
        (
            "valid_blank_probability_issue_only",
            "valid_blank_probability_issue",
            lambda r: r["is_valid"] and r["unscored_reason"] == "blank_probability_valid_issue",
        ),
    ]

    print()
    print("Self-check against _schema_notes.known_test_cases:")
    all_passed = True
    for note_key, label, predicate in checks:
        expected_ids = set(notes.get(note_key, []))
        actual_ids = {r["id"] for r in results if predicate(r)}
        if expected_ids == actual_ids:
            print(f"  OK   {label}: {sorted(expected_ids)}")
        else:
            all_passed = False
            print(f"  FAIL {label}: expected {sorted(expected_ids)}, got {sorted(actual_ids)}")
    print("All checks passed." if all_passed else "Some checks failed — see above.")


def main():
    parser = argparse.ArgumentParser(description="US-1/US-2: score and validate RAID log entries.")
    parser.add_argument("--data", default=None, help="Path to the mock RAID dataset seed (JSON or xlsx template)")
    parser.add_argument("--db", default=raid_store.DEFAULT_DB_PATH, help="Path to the persistent store (.db or .xlsx)")
    args = parser.parse_args()

    seed_path = args.data or raid_store.default_seed_path(args.db)
    dataset, entries = raid_data.load_converted_entries(seed_path, args.db)

    results = process(entries)
    print_report(results)
    self_check(dataset, results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
