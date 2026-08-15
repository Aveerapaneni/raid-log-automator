"""Unit tests for US-3: Days Open and Status auto-transition.

Synthetic entries with a fixed 'today' for deterministic Days Open math,
independent of raid_mock_data.json.
"""

import json
from datetime import date

import pytest

import raid_db
from days_and_status import compute_days_open, compute_status, load_and_process, persist_status_promotions, process, self_check

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


# ---------------------------------------------------------------------------
# persist_status_promotions / load_and_process — US-9 persistence
# ---------------------------------------------------------------------------

def db_entry(**overrides):
    base = {
        "id": "RAID-Z",
        "category": "Risk",
        "owner": "Test Owner",
        "mitigation_plan": "A plan",
        "probability": 3,
        "impact": 4,
        "date_raised": "2026-01-01",
        "start_date": None,
        "status": "Not Started",
        "materialized": False,
        "dependency_links": [],
        "blocked_by": [],
        "target_date": "2026-06-01",
        "last_updated": "2026-01-01",
    }
    base.update(overrides)
    return base


def write_seed(tmp_path, entries):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({"entries": entries}))
    return str(path)


def test_persist_status_promotions_writes_only_changed_entries(tmp_path):
    seed = write_seed(
        tmp_path,
        [db_entry(id="A", status="Not Started", start_date="2026-02-01"), db_entry(id="B", status="Not Started")],
    )
    db = str(tmp_path / "test.db")
    raid_db.ensure_db(db, seed)

    results = process(raid_db.load_entries(db), today=TODAY)
    persist_status_promotions(db, results)

    by_id = {e["id"]: e for e in raid_db.load_entries(db)}
    assert by_id["A"]["status"] == "In Progress"
    assert by_id["B"]["status"] == "Not Started"


def test_load_and_process_persists_promotion_and_reflects_it_on_second_call(tmp_path):
    seed = write_seed(tmp_path, [db_entry(id="A", status="Not Started", start_date="2026-02-01")])
    db = str(tmp_path / "test.db")

    dataset, results = load_and_process(db, seed, today=TODAY)
    assert results[0]["status"] == "In Progress"
    assert results[0]["status_changed"] is True

    # Second call: already promoted, so no *new* transition this run --
    # status stays In Progress but status_changed is now False.
    dataset2, results2 = load_and_process(db, seed, today=TODAY)
    assert results2[0]["status"] == "In Progress"
    assert results2[0]["status_changed"] is False


def test_load_and_process_also_applies_and_persists_materialize_conversion(tmp_path):
    seed = write_seed(tmp_path, [db_entry(id="A", category="Risk", materialized=True, status="Monitoring")])
    db = str(tmp_path / "test.db")

    _, results = load_and_process(db, seed, today=TODAY)
    assert results[0]["category"] == "Issue"

    stored = raid_db.load_entries(db)
    assert stored[0]["category"] == "Issue"


def test_self_check_passes_on_a_second_run_even_though_status_changed_is_now_false(tmp_path, capsys):
    # Regression test for a real bug: self_check used to assert
    # status_changed=True for known-promoted IDs, which only holds on
    # the very first run against a fresh db. Once persisted (US-9), the
    # second run correctly reports status_changed=False -- self_check
    # must judge by final Status, not by whether *this* run did the
    # promoting.
    dataset = {
        "_schema_notes": {
            "known_test_cases": {"start_date_set_but_status_not_updated": ["A"]}
        }
    }
    seed = write_seed(tmp_path, [db_entry(id="A", status="Not Started", start_date="2026-02-01")])
    db = str(tmp_path / "test.db")

    _, first_results = load_and_process(db, seed, today=TODAY)
    self_check(dataset, first_results)
    assert "FAIL" not in capsys.readouterr().out

    _, second_results = load_and_process(db, seed, today=TODAY)
    assert second_results[0]["status_changed"] is False  # already promoted
    self_check(dataset, second_results)
    assert "FAIL" not in capsys.readouterr().out
