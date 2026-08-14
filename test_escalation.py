"""Unit tests for US-4: runtime-configurable escalation.

Covers breach logic against synthetic records, idempotency (already
Escalated/Closed never re-trigger), and the Section 9 refuse-rather-than-
default behavior when no threshold is supplied.
"""

import pytest

from escalation import (
    apply_escalations,
    breaches_threshold,
    resolve_days_open_threshold,
    resolve_score_band,
)


def record(**overrides):
    base = {
        "id": "TEST-0",
        "category": "Risk",
        "status": "In Progress",
        "days_open": 100,
        "priority_score": 16,
        "priority_bucket": "High",
        "scorable": True,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# breaches_threshold
# ---------------------------------------------------------------------------

def test_high_priority_aged_entry_breaches():
    assert breaches_threshold(record(), score_band="High", days_open_threshold=60) is True


def test_below_score_band_does_not_breach():
    r = record(priority_bucket="Medium", priority_score=12)
    assert breaches_threshold(r, score_band="High", days_open_threshold=60) is False


def test_below_days_open_threshold_does_not_breach():
    r = record(days_open=10)
    assert breaches_threshold(r, score_band="High", days_open_threshold=60) is False


def test_exact_threshold_values_do_breach():
    r = record(days_open=60, priority_bucket="High")
    assert breaches_threshold(r, score_band="High", days_open_threshold=60) is True


@pytest.mark.parametrize("status", ["Closed", "Escalated"])
def test_closed_or_already_escalated_never_breaches(status):
    r = record(status=status)
    assert breaches_threshold(r, score_band="Low", days_open_threshold=0) is False


def test_unscored_entry_never_breaches_even_if_aged():
    r = record(scorable=False, priority_bucket=None, priority_score=None, days_open=9999)
    assert breaches_threshold(r, score_band="Low", days_open_threshold=0) is False


def test_missing_days_open_never_breaches():
    r = record(days_open=None)
    assert breaches_threshold(r, score_band="Low", days_open_threshold=0) is False


def test_medium_band_admits_medium_and_high_but_not_low():
    high = record(priority_bucket="High")
    medium = record(priority_bucket="Medium", priority_score=12)
    low = record(priority_bucket="Low", priority_score=4)
    assert breaches_threshold(high, "Medium", 0) is True
    assert breaches_threshold(medium, "Medium", 0) is True
    assert breaches_threshold(low, "Medium", 0) is False


# ---------------------------------------------------------------------------
# apply_escalations
# ---------------------------------------------------------------------------

def test_apply_escalations_produces_event_and_updated_status():
    records = [record(id="RAID-X")]
    updated, events = apply_escalations(records, "High", 60, timestamp="2026-08-14T00:00:00Z")
    assert updated[0]["status"] == "Escalated"
    assert len(events) == 1
    assert events[0]["id"] == "RAID-X"
    assert events[0]["previous_status"] == "In Progress"
    assert events[0]["new_status"] == "Escalated"
    assert events[0]["timestamp"] == "2026-08-14T00:00:00Z"


def test_apply_escalations_does_not_mutate_input_records():
    records = [record(id="RAID-X")]
    original_status_id = id(records[0])
    apply_escalations(records, "High", 60)
    assert records[0]["status"] == "In Progress"  # untouched
    assert id(records[0]) == original_status_id


def test_apply_escalations_is_idempotent_within_a_single_pass():
    records = [record(id="RAID-X")]
    updated_once, events_once = apply_escalations(records, "High", 60)
    updated_twice, events_twice = apply_escalations(updated_once, "High", 60)
    assert len(events_once) == 1
    assert len(events_twice) == 0
    assert updated_twice[0]["status"] == "Escalated"


def test_apply_escalations_leaves_non_breaching_records_untouched():
    records = [record(id="RAID-X", days_open=1)]
    updated, events = apply_escalations(records, "High", 60)
    assert events == []
    assert updated[0] is records[0]


@pytest.mark.parametrize("bad_band", ["Urgent", "high", None, ""])
def test_apply_escalations_rejects_invalid_score_band(bad_band):
    with pytest.raises(ValueError):
        apply_escalations([record()], bad_band, 60)


@pytest.mark.parametrize("bad_days", [-1, -100, "60", None])
def test_apply_escalations_rejects_invalid_days_open_threshold(bad_days):
    with pytest.raises(ValueError):
        apply_escalations([record()], "High", bad_days)


# ---------------------------------------------------------------------------
# resolve_score_band / resolve_days_open_threshold — Section 9: refuse rather
# than silently default when no threshold is supplied.
# ---------------------------------------------------------------------------

def test_resolve_score_band_accepts_valid_cli_value():
    assert resolve_score_band("Medium") == "Medium"


def test_resolve_score_band_prompts_when_not_supplied():
    assert resolve_score_band(None, prompt=lambda _: "High") == "High"


def test_resolve_score_band_refuses_invalid_value():
    with pytest.raises(ValueError):
        resolve_score_band("Urgent")


def test_resolve_score_band_refuses_empty_prompt_response():
    with pytest.raises(ValueError):
        resolve_score_band(None, prompt=lambda _: "")


def test_resolve_days_open_threshold_accepts_valid_cli_value():
    assert resolve_days_open_threshold(30) == 30


def test_resolve_days_open_threshold_prompts_when_not_supplied():
    assert resolve_days_open_threshold(None, prompt=lambda _: "45") == 45


def test_resolve_days_open_threshold_refuses_blank_prompt_response():
    with pytest.raises(ValueError):
        resolve_days_open_threshold(None, prompt=lambda _: "   ")


def test_resolve_days_open_threshold_refuses_non_integer():
    with pytest.raises(ValueError):
        resolve_days_open_threshold(None, prompt=lambda _: "soon")


def test_resolve_days_open_threshold_refuses_negative():
    with pytest.raises(ValueError):
        resolve_days_open_threshold(-5)
