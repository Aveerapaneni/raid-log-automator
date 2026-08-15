"""Unit tests for US-5: Materialized-Risk -> Issue auto-conversion.

Includes the Section 9 idempotency edge case directly: reprocessing a
dataset that already went through one conversion pass must not create a
duplicate or re-fire the conversion.
"""

import json

import pytest

import raid_db
from materialize_conversion import (
    convert_entry,
    is_materialized_risk,
    load_and_convert,
    persist_conversions,
    process,
    self_check,
)


def entry(**overrides):
    base = {
        "id": "TEST-0",
        "category": "Risk",
        "owner": "Test Owner",
        "materialized": False,
        "mitigation_plan": "Some plan",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# is_materialized_risk / convert_entry
# ---------------------------------------------------------------------------

def test_materialized_risk_is_detected():
    assert is_materialized_risk(entry(category="Risk", materialized=True)) is True


@pytest.mark.parametrize("category", ["Assumption", "Issue", "Dependency"])
def test_materialized_flag_on_non_risk_category_is_not_a_conversion_target(category):
    assert is_materialized_risk(entry(category=category, materialized=True)) is False


def test_unmaterialized_risk_is_not_a_conversion_target():
    assert is_materialized_risk(entry(category="Risk", materialized=False)) is False


def test_risk_with_no_materialized_field_is_not_a_conversion_target():
    e = entry(category="Risk")
    del e["materialized"]
    assert is_materialized_risk(e) is False


def test_convert_entry_updates_category_and_flags_converted():
    new_entry, converted = convert_entry(entry(id="RAID-X", category="Risk", materialized=True))
    assert converted is True
    assert new_entry["category"] == "Issue"
    assert new_entry["id"] == "RAID-X"


def test_convert_entry_preserves_all_other_fields_as_history():
    original = entry(
        id="RAID-X",
        category="Risk",
        materialized=True,
        owner="Sam Whitfield",
        mitigation_plan="Add a transformation layer",
    )
    new_entry, _ = convert_entry(original)
    assert new_entry["owner"] == "Sam Whitfield"
    assert new_entry["mitigation_plan"] == "Add a transformation layer"
    assert new_entry["materialized"] is True  # kept as historical fact, not cleared


def test_convert_entry_does_not_mutate_the_original():
    original = entry(id="RAID-X", category="Risk", materialized=True)
    convert_entry(original)
    assert original["category"] == "Risk"


def test_non_materialized_entry_passes_through_unconverted_and_is_the_same_object():
    original = entry(id="RAID-Y", category="Risk", materialized=False)
    new_entry, converted = convert_entry(original)
    assert converted is False
    assert new_entry is original


# ---------------------------------------------------------------------------
# process — batch conversion + idempotency on reprocessing
# ---------------------------------------------------------------------------

def test_process_converts_only_materialized_risks_in_a_mixed_batch():
    entries = [
        entry(id="R1", category="Risk", materialized=True),
        entry(id="R2", category="Risk", materialized=False),
        entry(id="A1", category="Assumption", materialized=None),
        entry(id="I1", category="Issue", materialized=None),
    ]
    updated, events = process(entries)
    converted_ids = {e["id"] for e in events}
    assert converted_ids == {"R1"}
    by_id = {e["id"]: e for e in updated}
    assert by_id["R1"]["category"] == "Issue"
    assert by_id["R2"]["category"] == "Risk"
    assert by_id["A1"]["category"] == "Assumption"
    assert by_id["I1"]["category"] == "Issue"


def test_process_preserves_entry_order():
    entries = [entry(id="R1"), entry(id="R2"), entry(id="R3")]
    updated, _ = process(entries)
    assert [e["id"] for e in updated] == ["R1", "R2", "R3"]


def test_reprocessing_a_materialized_risk_twice_is_idempotent_no_duplicate_conversion():
    entries = [entry(id="RAID-X", category="Risk", materialized=True)]

    first_pass, first_events = process(entries)
    assert len(first_events) == 1
    assert first_pass[0]["category"] == "Issue"

    second_pass, second_events = process(first_pass)
    assert second_events == []
    assert second_pass[0]["category"] == "Issue"
    assert len(second_pass) == 1  # no duplicate entry created


def test_reprocessing_never_grows_the_dataset_across_many_runs():
    entries = [entry(id="RAID-X", category="Risk", materialized=True)]
    current = entries
    for _ in range(5):
        current, _ = process(current)
    assert len(current) == 1
    assert current[0]["category"] == "Issue"


# ---------------------------------------------------------------------------
# persist_conversions / load_and_convert — US-9 persistence
# ---------------------------------------------------------------------------

def db_entry(**overrides):
    base = {
        "id": "RAID-X",
        "category": "Risk",
        "owner": "Test Owner",
        "mitigation_plan": "A plan",
        "probability": 3,
        "impact": 4,
        "date_raised": "2026-01-01",
        "start_date": None,
        "status": "Monitoring",
        "materialized": True,
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


def test_persist_conversions_writes_category_to_db(tmp_path):
    seed = write_seed(tmp_path, [db_entry()])
    db = str(tmp_path / "test.db")
    raid_db.ensure_db(db, seed)

    events = [{"id": "RAID-X", "previous_category": "Risk", "new_category": "Issue"}]
    persist_conversions(db, events)

    [stored] = raid_db.load_entries(db)
    assert stored["category"] == "Issue"


def test_persist_conversions_is_a_no_op_with_no_events(tmp_path):
    seed = write_seed(tmp_path, [db_entry(category="Risk", materialized=False)])
    db = str(tmp_path / "test.db")
    raid_db.ensure_db(db, seed)

    persist_conversions(db, [])

    [stored] = raid_db.load_entries(db)
    assert stored["category"] == "Risk"


def test_load_and_convert_persists_and_reports_only_new_conversions_this_run(tmp_path):
    seed = write_seed(tmp_path, [db_entry(id="RAID-X", materialized=True)])
    db = str(tmp_path / "test.db")

    dataset, entries, events = load_and_convert(db, seed)
    assert [e["id"] for e in events] == ["RAID-X"]
    assert entries[0]["category"] == "Issue"

    # Second call against the same db: already converted, so no new events
    # this run -- even though the entry itself remains an Issue.
    dataset2, entries2, events2 = load_and_convert(db, seed)
    assert events2 == []
    assert entries2[0]["category"] == "Issue"


def test_self_check_passes_on_a_second_run_even_though_events_are_now_empty(tmp_path, capsys):
    # Regression test for a real bug: self_check used to assert the
    # expected id appeared in `events`, which only holds on the very
    # first run against a fresh db. Once persisted (US-9), the second
    # run correctly reports zero new events -- self_check must judge by
    # final Category, not by whether *this* run did the converting.
    dataset = {
        "_schema_notes": {"known_test_cases": {"materialized_risk_should_convert_to_issue": ["RAID-X"]}}
    }
    seed = write_seed(tmp_path, [db_entry(id="RAID-X", materialized=True)])
    db = str(tmp_path / "test.db")

    _, first_entries, first_events = load_and_convert(db, seed)
    self_check(dataset, first_entries, first_events)
    assert "FAIL" not in capsys.readouterr().out

    _, second_entries, second_events = load_and_convert(db, seed)
    assert second_events == []  # already converted
    self_check(dataset, second_entries, second_events)
    assert "FAIL" not in capsys.readouterr().out
