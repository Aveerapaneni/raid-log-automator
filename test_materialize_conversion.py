"""Unit tests for US-5: Materialized-Risk -> Issue auto-conversion.

Includes the Section 9 idempotency edge case directly: reprocessing a
dataset that already went through one conversion pass must not create a
duplicate or re-fire the conversion.
"""

import pytest

from materialize_conversion import convert_entry, is_materialized_risk, process


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
