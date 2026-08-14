"""Unit tests for US-4: runtime-configurable escalation.

Covers breach logic against synthetic records, idempotency (already
Escalated/Closed never re-trigger), the Section 9 refuse-rather-than-
default behavior when no threshold is supplied, and the two integration
points that were previously only exercised by manual CLI runs:
build_records() (merges US-1/US-3 output) and append_log() (the audit
trail the "logged with a timestamp" acceptance criterion depends on).
"""

import json
from datetime import date

import pytest

from escalation import (
    append_log,
    apply_escalations,
    breaches_threshold,
    build_records,
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


# ---------------------------------------------------------------------------
# build_records — merges US-1 (priority) and US-3 (effective status/days
# open) per entry. Previously only exercised by a manual CLI run.
# ---------------------------------------------------------------------------

def raid_entry(**overrides):
    base = {
        "id": "T-1",
        "category": "Risk",
        "owner": "Test Owner",
        "date_raised": "2026-08-01",
        "start_date": None,
        "status": "Not Started",
        "probability": 4,
        "impact": 4,
        "mitigation_plan": "Some plan",
    }
    base.update(overrides)
    return base


def test_build_records_computes_priority_and_days_open():
    entries = [raid_entry(id="T-1", probability=4, impact=4, date_raised="2026-08-01")]
    [record] = build_records(entries, today=date(2026, 8, 14))
    assert record["id"] == "T-1"
    assert record["priority_score"] == 16
    assert record["priority_bucket"] == "High"
    assert record["scorable"] is True
    assert record["days_open"] == 13


def test_build_records_uses_effective_status_not_raw_status():
    # Raw status is "Not Started" but Start Date is set -- build_records
    # should reflect the US-3 auto-promotion to "In Progress", not the
    # untouched raw field.
    entries = [
        raid_entry(
            id="T-2",
            category="Issue",
            status="Not Started",
            start_date="2026-07-05",
            date_raised="2026-07-01",
            probability=None,
        )
    ]
    [record] = build_records(entries, today=date(2026, 8, 14))
    assert record["status"] == "In Progress"
    assert record["days_open"] == 44
    assert record["scorable"] is False  # blank Probability on an Issue


def test_build_records_preserves_entry_order_and_handles_multiple_ids():
    entries = [raid_entry(id="T-1"), raid_entry(id="T-2"), raid_entry(id="T-3")]
    records = build_records(entries, today=date(2026, 8, 14))
    assert [r["id"] for r in records] == ["T-1", "T-2", "T-3"]


# ---------------------------------------------------------------------------
# append_log — the audit trail US-4's "logged with a timestamp" acceptance
# criterion depends on. Previously untested: nothing proved a second run
# appends rather than overwrites.
# ---------------------------------------------------------------------------

def sample_event(event_id="RAID-X"):
    return {
        "timestamp": "2026-08-14T00:00:00+00:00",
        "id": event_id,
        "category": "Risk",
        "previous_status": "In Progress",
        "new_status": "Escalated",
        "priority_score": 16,
        "priority_bucket": "High",
        "days_open": 94,
        "score_band_threshold": "High",
        "days_open_threshold": 60,
    }


def test_append_log_writes_one_json_line_per_event(tmp_path):
    log_path = tmp_path / "escalation_log.jsonl"
    append_log([sample_event("RAID-A"), sample_event("RAID-B")], str(log_path))

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert [p["id"] for p in parsed] == ["RAID-A", "RAID-B"]
    assert parsed[0]["new_status"] == "Escalated"


def test_append_log_appends_across_calls_without_overwriting(tmp_path):
    log_path = tmp_path / "escalation_log.jsonl"
    append_log([sample_event("RAID-A")], str(log_path))
    append_log([sample_event("RAID-B")], str(log_path))

    lines = log_path.read_text().strip().splitlines()
    ids = [json.loads(line)["id"] for line in lines]
    assert ids == ["RAID-A", "RAID-B"]


def test_append_log_is_a_no_op_with_no_events_and_creates_no_file(tmp_path):
    log_path = tmp_path / "escalation_log.jsonl"
    append_log([], str(log_path))
    assert not log_path.exists()
