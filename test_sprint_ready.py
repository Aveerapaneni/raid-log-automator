"""Unit tests for US-8: the Sprint Ready pile.

Synthetic entries with a fixed 'today', independent of raid_mock_data.json,
covering eligibility rules, tier/bucket/date ordering, and true-tie
detection per Section 9.
"""

from datetime import date

import pytest

from sprint_ready import build_pile, is_eligible, print_report

TODAY = date(2026, 8, 14)


def entry(**overrides):
    base = {
        "id": "TEST-0",
        "category": "Risk",
        "owner": "Test Owner",
        "probability": 4,
        "impact": 4,
        "mitigation_plan": "Some plan",
        "date_raised": "2026-06-01",
        "start_date": "2026-06-05",
        "status": "In Progress",
        "blocked_by": [],
    }
    base.update(overrides)
    return base


def candidate_for(entry_dict, entries=None):
    from sprint_ready import build_pile_candidates

    entries = entries if entries is not None else [entry_dict]
    [c] = [c for c in build_pile_candidates(entries, today=TODAY) if c["id"] == entry_dict["id"]]
    return c


# ---------------------------------------------------------------------------
# is_eligible
# ---------------------------------------------------------------------------

def test_fully_complete_unblocked_open_entry_is_eligible():
    c = candidate_for(entry())
    assert is_eligible(c) is True


def test_invalid_entry_missing_owner_is_not_eligible():
    c = candidate_for(entry(owner=None))
    assert is_eligible(c) is False


def test_missing_start_date_is_not_eligible():
    c = candidate_for(entry(start_date=None))
    assert is_eligible(c) is False


def test_blocked_entry_is_not_eligible():
    c = candidate_for(entry(blocked_by=["OTHER-1"]))
    assert is_eligible(c) is False


def test_closed_entry_is_not_eligible_even_if_otherwise_complete():
    c = candidate_for(entry(status="Closed"))
    assert is_eligible(c) is False


def test_unscored_but_valid_issue_is_eligible():
    c = candidate_for(entry(category="Issue", probability=None))
    assert c["scorable"] is False
    assert is_eligible(c) is True


def test_entry_promoted_by_us3_start_date_rule_is_eligible_not_excluded_as_closed():
    # Not Started + Start Date set -> effective status In Progress (US-3),
    # so it must not be excluded as if it were still Not Started/Closed.
    c = candidate_for(entry(status="Not Started", start_date="2026-06-05"))
    assert c["status"] == "In Progress"
    assert is_eligible(c) is True


# ---------------------------------------------------------------------------
# build_pile: ordering
# ---------------------------------------------------------------------------

def test_unscored_issue_sorts_ahead_of_every_scored_entry_regardless_of_date():
    entries = [
        entry(id="HIGH", category="Risk", probability=5, impact=5, date_raised="2026-01-01"),
        entry(id="UNSCORED", category="Issue", probability=None, date_raised="2026-12-01"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert [c["id"] for c in pile] == ["UNSCORED", "HIGH"]


def test_scored_entries_ordered_high_then_medium_then_low():
    entries = [
        entry(id="LOW", probability=1, impact=2, date_raised="2026-01-01"),
        entry(id="HIGH", probability=5, impact=5, date_raised="2026-01-01"),
        entry(id="MEDIUM", probability=3, impact=4, date_raised="2026-01-01"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert [c["id"] for c in pile] == ["HIGH", "MEDIUM", "LOW"]


def test_same_bucket_ties_broken_by_earlier_date_raised_first():
    entries = [
        entry(id="LATER", probability=4, impact=4, date_raised="2026-03-01"),
        entry(id="EARLIER", probability=4, impact=4, date_raised="2026-01-01"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert [c["id"] for c in pile] == ["EARLIER", "LATER"]


def test_unscored_entries_among_themselves_ordered_by_earlier_date_raised():
    entries = [
        entry(id="LATER", category="Issue", probability=None, date_raised="2026-03-01"),
        entry(id="EARLIER", category="Issue", probability=None, date_raised="2026-01-01"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert [c["id"] for c in pile] == ["EARLIER", "LATER"]


def test_ineligible_entries_are_excluded_from_the_pile():
    entries = [entry(id="OK"), entry(id="BLOCKED", blocked_by=["OK"])]
    pile = build_pile(entries, today=TODAY)
    assert [c["id"] for c in pile] == ["OK"]


def test_empty_pile_when_nothing_qualifies():
    entries = [entry(id="CLOSED", status="Closed")]
    pile = build_pile(entries, today=TODAY)
    assert pile == []


def test_print_report_handles_empty_pile_without_crashing(capsys):
    print_report([])
    out = capsys.readouterr().out
    assert "empty" in out.lower()


# ---------------------------------------------------------------------------
# True-tie detection (Section 9)
# ---------------------------------------------------------------------------

def test_same_bucket_and_same_date_raised_is_flagged_as_a_true_tie():
    entries = [
        entry(id="A", probability=4, impact=4, date_raised="2026-06-05"),
        entry(id="B", probability=4, impact=4, date_raised="2026-06-05"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert all(c["is_tie"] for c in pile)


def test_same_bucket_different_date_is_not_a_tie():
    entries = [
        entry(id="A", probability=4, impact=4, date_raised="2026-06-05"),
        entry(id="B", probability=4, impact=4, date_raised="2026-06-06"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert not any(c["is_tie"] for c in pile)


def test_same_date_different_bucket_is_not_a_tie():
    entries = [
        entry(id="A", probability=5, impact=5, date_raised="2026-06-05"),  # High
        entry(id="B", probability=3, impact=4, date_raised="2026-06-05"),  # Medium
    ]
    pile = build_pile(entries, today=TODAY)
    assert not any(c["is_tie"] for c in pile)


def test_two_unscored_issues_same_date_raised_is_also_a_true_tie():
    entries = [
        entry(id="A", category="Issue", probability=None, date_raised="2026-06-05"),
        entry(id="B", category="Issue", probability=None, date_raised="2026-06-05"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert all(c["is_tie"] for c in pile)


def test_unscored_and_scored_never_tie_with_each_other():
    entries = [
        entry(id="UNSCORED", category="Issue", probability=None, date_raised="2026-06-05"),
        entry(id="SCORED", probability=4, impact=4, date_raised="2026-06-05"),
    ]
    pile = build_pile(entries, today=TODAY)
    assert not any(c["is_tie"] for c in pile)


def test_three_way_tie_all_three_flagged():
    entries = [
        entry(id="A", probability=4, impact=4, date_raised="2026-06-05"),
        entry(id="B", probability=4, impact=4, date_raised="2026-06-05"),
        entry(id="C", probability=3, impact=4, date_raised="2026-06-01"),  # same bucket, different date
    ]
    pile = build_pile(entries, today=TODAY)
    by_id = {c["id"]: c for c in pile}
    assert by_id["A"]["is_tie"] is True
    assert by_id["B"]["is_tie"] is True
    assert by_id["C"]["is_tie"] is False
