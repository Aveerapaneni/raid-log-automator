"""Unit tests for US-6: the manually-triggered digest.

Synthetic entries with a fixed 'today', independent of raid_mock_data.json.
Special attention to the bug caught during manual verification: an entry
that's unscored *because it's invalid* (missing Probability on a non-Issue
category) must never get the same top billing as the one sanctioned
unscored case (a valid Issue with blank Probability).
"""

from datetime import date

import pytest

from digest import (
    build_digest_candidates,
    format_digest,
    group_by_category,
    is_digest_eligible,
    select_top_items,
)

TODAY = date(2026, 8, 14)


def entry(**overrides):
    base = {
        "id": "TEST-0",
        "category": "Risk",
        "description": "Something that needs attention.",
        "owner": "Test Owner",
        "probability": 4,
        "impact": 4,
        "mitigation_plan": "Some plan",
        "date_raised": "2026-06-01",
        "start_date": "2026-06-05",
        "status": "In Progress",
    }
    base.update(overrides)
    return base


def candidate_for(entry_dict, entries=None):
    entries = entries if entries is not None else [entry_dict]
    [c] = [c for c in build_digest_candidates(entries, today=TODAY) if c["id"] == entry_dict["id"]]
    return c


# ---------------------------------------------------------------------------
# is_digest_eligible
# ---------------------------------------------------------------------------

def test_open_scored_valid_entry_is_eligible():
    c = candidate_for(entry())
    assert is_digest_eligible(c) is True


def test_closed_entry_is_not_eligible():
    c = candidate_for(entry(status="Closed"))
    assert is_digest_eligible(c) is False


def test_valid_unscored_issue_is_eligible():
    c = candidate_for(entry(category="Issue", probability=None))
    assert c["scorable"] is False
    assert c["is_valid"] is True
    assert is_digest_eligible(c) is True


def test_invalid_unscored_non_issue_is_not_eligible():
    # This is the exact bug caught manually: missing Probability on a
    # Risk/Assumption/Dependency makes it invalid AND unscored -- it must
    # not be treated the same as a valid unscored Issue.
    c = candidate_for(entry(category="Risk", probability=None))
    assert c["scorable"] is False
    assert c["is_valid"] is False
    assert is_digest_eligible(c) is False


def test_invalid_but_scored_entry_is_still_eligible():
    # Missing Mitigation Plan makes a Risk invalid, but it still has a
    # computable Priority and a high-priority gap is exactly what a
    # digest should surface.
    c = candidate_for(entry(mitigation_plan=None))
    assert c["scorable"] is True
    assert c["is_valid"] is False
    assert is_digest_eligible(c) is True


# ---------------------------------------------------------------------------
# select_top_items: ranking, count bounds, tie-breaking
# ---------------------------------------------------------------------------

def test_unscored_valid_issue_ranks_ahead_of_every_scored_entry():
    entries = [
        entry(id="HIGH", probability=5, impact=5, date_raised="2026-01-01"),
        entry(id="UNSCORED", category="Issue", probability=None, date_raised="2026-12-01"),
    ]
    top = select_top_items(entries, count=3, today=TODAY)
    assert [i["id"] for i in top] == ["UNSCORED", "HIGH"]


def test_scored_entries_ranked_by_descending_priority_score():
    entries = [
        entry(id="LOW", probability=1, impact=2, date_raised="2026-01-01"),
        entry(id="HIGH", probability=5, impact=5, date_raised="2026-01-01"),
        entry(id="MEDIUM", probability=3, impact=4, date_raised="2026-01-01"),
    ]
    top = select_top_items(entries, count=3, today=TODAY)
    assert [i["id"] for i in top] == ["HIGH", "MEDIUM", "LOW"]


def test_tied_score_broken_by_earlier_date_raised_first():
    entries = [
        entry(id="LATER", probability=4, impact=4, date_raised="2026-03-01"),
        entry(id="EARLIER", probability=4, impact=4, date_raised="2026-01-01"),
    ]
    top = select_top_items(entries, count=3, today=TODAY)
    assert [i["id"] for i in top] == ["EARLIER", "LATER"]


def test_selection_is_cut_to_count():
    entries = [entry(id=f"R{i}", probability=5, impact=5, date_raised="2026-01-01") for i in range(10)]
    top = select_top_items(entries, count=3, today=TODAY)
    assert len(top) == 3


def test_closed_entries_never_selected():
    entries = [entry(id="OPEN"), entry(id="CLOSED", status="Closed", probability=5, impact=5)]
    top = select_top_items(entries, count=5, today=TODAY)
    assert "CLOSED" not in [i["id"] for i in top]


def test_invalid_unscored_entries_never_selected_even_when_pile_is_short():
    entries = [entry(id="INVALID", probability=None)]  # Risk, missing Probability -> invalid
    top = select_top_items(entries, count=5, today=TODAY)
    assert top == []


@pytest.mark.parametrize("bad_count", [0, 1, 2, 6, 100, -1])
def test_count_outside_3_to_5_is_rejected(bad_count):
    with pytest.raises(ValueError):
        select_top_items([entry()], count=bad_count, today=TODAY)


# ---------------------------------------------------------------------------
# group_by_category / format_digest — presentation
# ---------------------------------------------------------------------------

def test_group_by_category_buckets_correctly():
    items = [
        candidate_for(entry(id="R1", category="Risk")),
        candidate_for(entry(id="I1", category="Issue", probability=None)),
    ]
    grouped = group_by_category(items)
    assert [c["id"] for c in grouped["Risk"]] == ["R1"]
    assert [c["id"] for c in grouped["Issue"]] == ["I1"]


def test_format_digest_handles_empty_selection_without_crashing():
    output = format_digest([], "2026-08-14")
    assert "No open items" in output


def test_format_digest_includes_id_owner_and_priority_for_each_item():
    top = select_top_items([entry(id="RAID-X", owner="Jordan Lee")], count=3, today=TODAY)
    output = format_digest(top, "2026-08-14")
    assert "RAID-X" in output
    assert "Jordan Lee" in output
    assert "High" in output


def test_format_digest_labels_unscored_items_distinctly_not_as_a_priority_bucket():
    top = select_top_items(
        [entry(id="RAID-X", category="Issue", probability=None)], count=3, today=TODAY
    )
    output = format_digest(top, "2026-08-14")
    assert "Unscored" in output
