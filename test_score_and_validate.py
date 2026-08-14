"""Unit tests for US-1 (priority scoring) and US-2 (log discipline validation).

These are synthetic entries, independent of raid_mock_data.json, aimed at the
boundary and invalid-range cases the mock dataset doesn't happen to exercise
(e.g. out-of-range Probability/Impact, an exact score of 8 or 15).

Note: valid Probability/Impact are each in {1..5}, so the only achievable
Priority scores are {1,2,3,4,5,6,8,9,10,12,15,16,20,25} — 7 and 14 can never
occur, so boundary tests use the nearest achievable values instead.
"""

import pytest

from score_and_validate import compute_priority, process, validate_entry


def entry(**overrides):
    base = {
        "id": "TEST-0",
        "category": "Risk",
        "owner": "Test Owner",
        "probability": 3,
        "impact": 3,
        "mitigation_plan": "Some plan",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# US-1: compute_priority
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "probability,impact,expected_score,expected_bucket",
    [
        (1, 1, 1, "Low"),
        (2, 3, 6, "Low"),
        (2, 4, 8, "Medium"),   # Low/Medium boundary
        (3, 4, 12, "Medium"),
        (3, 5, 15, "High"),    # Medium/High boundary
        (4, 4, 16, "High"),
        (5, 5, 25, "High"),
    ],
)
def test_compute_priority_buckets(probability, impact, expected_score, expected_bucket):
    score, bucket, scorable, reason = compute_priority(
        entry(probability=probability, impact=impact)
    )
    assert scorable is True
    assert reason is None
    assert score == expected_score
    assert bucket == expected_bucket


def test_missing_impact_is_unscored():
    score, bucket, scorable, reason = compute_priority(entry(impact=None))
    assert scorable is False
    assert score is None
    assert bucket is None
    assert reason == "missing_or_invalid_impact"


@pytest.mark.parametrize("bad_impact", [0, 6, -1])
def test_out_of_range_impact_is_unscored(bad_impact):
    score, bucket, scorable, reason = compute_priority(entry(impact=bad_impact))
    assert scorable is False
    assert reason == "missing_or_invalid_impact"


@pytest.mark.parametrize("category", ["Risk", "Assumption", "Dependency"])
def test_missing_probability_is_unscored_and_invalid_for_non_issue(category):
    score, bucket, scorable, reason = compute_priority(
        entry(category=category, probability=None)
    )
    assert scorable is False
    assert reason == "missing_probability_invalid"


def test_missing_probability_is_unscored_but_valid_for_issue():
    score, bucket, scorable, reason = compute_priority(
        entry(category="Issue", probability=None, mitigation_plan="Fix it")
    )
    assert scorable is False
    assert score is None
    assert bucket is None
    assert reason == "blank_probability_valid_issue"


@pytest.mark.parametrize("bad_probability", [0, 6, -1])
def test_out_of_range_probability_is_unscored(bad_probability):
    score, bucket, scorable, reason = compute_priority(entry(probability=bad_probability))
    assert scorable is False
    assert reason == "invalid_probability"


def test_out_of_range_probability_on_issue_is_still_unscored_not_treated_as_blank():
    # A present-but-invalid value is a different failure than an absent one,
    # even for Issue where absence is normally fine.
    score, bucket, scorable, reason = compute_priority(
        entry(category="Issue", probability=6, mitigation_plan="Fix it")
    )
    assert scorable is False
    assert reason == "invalid_probability"


# ---------------------------------------------------------------------------
# US-2: validate_entry
# ---------------------------------------------------------------------------

def test_fully_valid_entry_has_no_flags_or_warnings():
    flags, warnings = validate_entry(entry())
    assert flags == []
    assert warnings == []


@pytest.mark.parametrize("owner", [None, ""])
def test_missing_owner_is_flagged(owner):
    flags, warnings = validate_entry(entry(owner=owner))
    assert "missing_owner" in flags


@pytest.mark.parametrize(
    "owner", ["Platform Team", "Data Science Group", "Infra Dept", "Growth Squad"]
)
def test_owner_that_reads_like_a_team_is_a_warning_not_a_flag(owner):
    flags, warnings = validate_entry(entry(owner=owner))
    assert "missing_owner" not in flags
    assert "owner_is_likely_team" in warnings


def test_named_individual_owner_triggers_no_team_warning():
    flags, warnings = validate_entry(entry(owner="Maria Chen"))
    assert warnings == []


@pytest.mark.parametrize("category", ["Risk", "Issue"])
def test_missing_mitigation_plan_flagged_for_risk_and_issue(category):
    flags, warnings = validate_entry(entry(category=category, mitigation_plan=None))
    assert "missing_mitigation_plan" in flags


@pytest.mark.parametrize("category", ["Assumption", "Dependency"])
def test_missing_mitigation_plan_not_required_for_assumption_or_dependency(category):
    flags, warnings = validate_entry(entry(category=category, mitigation_plan=None))
    assert "missing_mitigation_plan" not in flags


def test_missing_probability_flagged_for_non_issue():
    flags, warnings = validate_entry(entry(category="Risk", probability=None))
    assert "missing_probability" in flags


def test_missing_probability_not_flagged_for_issue():
    flags, warnings = validate_entry(
        entry(category="Issue", probability=None, mitigation_plan="Fix it")
    )
    assert "missing_probability" not in flags


@pytest.mark.parametrize("bad_probability", [0, 6, -1])
def test_out_of_range_probability_is_flagged_even_for_issue(bad_probability):
    flags, warnings = validate_entry(
        entry(category="Issue", probability=bad_probability, mitigation_plan="Fix it")
    )
    assert "invalid_probability" in flags


def test_missing_impact_is_flagged():
    flags, warnings = validate_entry(entry(impact=None))
    assert "missing_impact" in flags


@pytest.mark.parametrize("bad_impact", [0, 6, -1])
def test_out_of_range_impact_is_flagged(bad_impact):
    flags, warnings = validate_entry(entry(impact=bad_impact))
    assert "invalid_impact" in flags


# ---------------------------------------------------------------------------
# process(): validity and scorability tracked independently
# ---------------------------------------------------------------------------

def test_process_valid_but_unscored_issue():
    [result] = process([entry(category="Issue", probability=None, mitigation_plan="Fix it")])
    assert result["is_valid"] is True
    assert result["scorable"] is False
    assert result["unscored_reason"] == "blank_probability_valid_issue"


def test_process_invalid_and_unscored_risk_missing_probability():
    [result] = process([entry(category="Risk", probability=None)])
    assert result["is_valid"] is False
    assert result["scorable"] is False
    assert "missing_probability" in result["flags"]


def test_process_valid_and_scored_entry():
    [result] = process([entry(probability=4, impact=4)])
    assert result["is_valid"] is True
    assert result["scorable"] is True
    assert result["priority_score"] == 16
    assert result["priority_bucket"] == "High"
