"""Unit tests for US-3: Days Open and Status auto-transition.

Synthetic entries with a fixed 'today' for deterministic Days Open math,
independent of raid_mock_data.json.
"""

from datetime import date

import pytest

from days_and_status import compute_days_open, compute_status, process

TODAY = date(2026, 8, 14)


def entry(**overrides):
    base = {
        "id": "TEST-0",
        "category": "Risk",
        "date_raised": "2026-08-01",
        "start_date": None,
        "status": "Not Started",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# compute_status
# ---------------------------------------------------------------------------

def test_not_started_with_start_date_promotes_to_in_progress():
    new_status, changed = compute_status(entry(status="Not Started", start_date="2026-08-05"))
    assert new_status == "In Progress"
    assert changed is True


def test_not_started_without_start_date_stays_not_started():
    new_status, changed = compute_status(entry(status="Not Started", start_date=None))
    assert new_status == "Not Started"
    assert changed is False


@pytest.mark.parametrize("status", ["In Progress", "Monitoring", "Escalated", "Closed"])
def test_non_not_started_statuses_are_never_altered_even_with_start_date(status):
    new_status, changed = compute_status(entry(status=status, start_date="2026-08-05"))
    assert new_status == status
    assert changed is False


def test_already_in_progress_is_idempotent_on_reprocessing():
    first_status, _ = compute_status(entry(status="Not Started", start_date="2026-08-05"))
    second_status, second_changed = compute_status(entry(status=first_status, start_date="2026-08-05"))
    assert second_status == "In Progress"
    assert second_changed is False


# ---------------------------------------------------------------------------
# compute_days_open
# ---------------------------------------------------------------------------

def test_days_open_counts_from_date_raised_to_today():
    days = compute_days_open(entry(date_raised="2026-08-01"), effective_status="Not Started", today=TODAY)
    assert days == 13


def test_days_open_is_zero_when_raised_today():
    days = compute_days_open(entry(date_raised="2026-08-14"), effective_status="Not Started", today=TODAY)
    assert days == 0


def test_days_open_is_blank_when_effective_status_is_closed():
    days = compute_days_open(entry(date_raised="2026-01-01"), effective_status="Closed", today=TODAY)
    assert days is None


def test_days_open_ignores_original_status_uses_effective_status():
    # Even if the raw record still says "Not Started", a Closed *effective*
    # status (post auto-transition) should blank Days Open.
    days = compute_days_open(entry(date_raised="2026-01-01", status="Not Started"), effective_status="Closed", today=TODAY)
    assert days is None


# ---------------------------------------------------------------------------
# process(): integration of both rules per entry
# ---------------------------------------------------------------------------

def test_process_promotes_status_and_computes_days_open_together():
    [result] = process(
        [entry(status="Not Started", start_date="2026-08-01", date_raised="2026-07-01")],
        today=TODAY,
    )
    assert result["status"] == "In Progress"
    assert result["status_changed"] is True
    assert result["days_open"] == 44


def test_process_closed_entry_has_blank_days_open_and_unchanged_status():
    [result] = process(
        [entry(status="Closed", start_date="2026-01-01", date_raised="2026-01-01")],
        today=TODAY,
    )
    assert result["status"] == "Closed"
    assert result["status_changed"] is False
    assert result["days_open"] is None


def test_process_defaults_today_to_real_current_date_when_not_supplied():
    [result] = process([entry(date_raised=date.today().isoformat())])
    assert result["days_open"] == 0
