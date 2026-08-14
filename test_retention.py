"""Unit tests for US-7: closed-entry retention.

Entries are never deleted, regardless of Status — Closed included. Status
can be set to Closed (an allowed transition), which is distinct from
removal (always refused).
"""

import pytest

from retention import RetentionError, close_entry, get_entry, list_entries, remove_entry


def entry(**overrides):
    base = {"id": "TEST-0", "category": "Risk", "status": "In Progress"}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# get_entry / list_entries
# ---------------------------------------------------------------------------

def test_get_entry_finds_by_id():
    entries = [entry(id="A"), entry(id="B")]
    assert get_entry(entries, "B")["id"] == "B"


def test_get_entry_raises_key_error_when_missing():
    with pytest.raises(KeyError):
        get_entry([entry(id="A")], "MISSING")


def test_list_entries_includes_closed_by_default():
    entries = [entry(id="A", status="Closed"), entry(id="B", status="In Progress")]
    assert {e["id"] for e in list_entries(entries)} == {"A", "B"}


def test_list_entries_can_exclude_closed():
    entries = [entry(id="A", status="Closed"), entry(id="B", status="In Progress")]
    assert {e["id"] for e in list_entries(entries, include_closed=False)} == {"B"}


def test_list_entries_never_drops_a_closed_entry_from_the_underlying_dataset():
    # Excluding from a *view* is not the same as removing from the *dataset*.
    entries = [entry(id="A", status="Closed")]
    filtered_out = list_entries(entries, include_closed=False)
    assert filtered_out == []
    assert get_entry(entries, "A") is entries[0]  # still there, still queryable


# ---------------------------------------------------------------------------
# close_entry — the allowed lifecycle transition
# ---------------------------------------------------------------------------

def test_close_entry_sets_status_to_closed():
    entries = [entry(id="A", status="In Progress")]
    updated = close_entry(entries, "A")
    assert get_entry(updated, "A")["status"] == "Closed"


def test_close_entry_does_not_remove_the_entry():
    entries = [entry(id="A")]
    updated = close_entry(entries, "A")
    assert len(updated) == 1


def test_close_entry_leaves_other_entries_untouched():
    entries = [entry(id="A"), entry(id="B", status="Monitoring")]
    updated = close_entry(entries, "A")
    assert get_entry(updated, "B")["status"] == "Monitoring"


def test_close_entry_does_not_mutate_the_original_list_or_dicts():
    entries = [entry(id="A", status="In Progress")]
    close_entry(entries, "A")
    assert entries[0]["status"] == "In Progress"


def test_close_entry_on_missing_id_raises_key_error():
    with pytest.raises(KeyError):
        close_entry([entry(id="A")], "MISSING")


def test_closing_an_already_closed_entry_is_a_harmless_no_op():
    entries = [entry(id="A", status="Closed")]
    updated = close_entry(entries, "A")
    assert get_entry(updated, "A")["status"] == "Closed"
    assert len(updated) == 1


# ---------------------------------------------------------------------------
# remove_entry — always refused, per Section 9
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["Not Started", "In Progress", "Monitoring", "Escalated"])
def test_remove_is_refused_for_open_entries_regardless_of_status(status):
    entries = [entry(id="A", status=status)]
    with pytest.raises(RetentionError):
        remove_entry(entries, "A")


def test_remove_is_refused_for_closed_entries_the_exact_section_9_scenario():
    entries = [entry(id="A", status="Closed")]
    with pytest.raises(RetentionError):
        remove_entry(entries, "A")


def test_remove_refusal_message_names_the_entry_and_explains_why():
    entries = [entry(id="RAID-008", status="Closed")]
    with pytest.raises(RetentionError, match="RAID-008"):
        remove_entry(entries, "RAID-008")


def test_remove_never_actually_shrinks_the_dataset():
    entries = [entry(id="A", status="Closed")]
    try:
        remove_entry(entries, "A")
    except RetentionError:
        pass
    assert len(entries) == 1
    assert get_entry(entries, "A") is not None


def test_remove_on_missing_id_raises_key_error_not_retention_error():
    with pytest.raises(KeyError):
        remove_entry([entry(id="A")], "MISSING")


def test_closing_then_attempting_removal_is_still_refused():
    entries = [entry(id="A", status="In Progress")]
    closed = close_entry(entries, "A")
    with pytest.raises(RetentionError):
        remove_entry(closed, "A")
    assert get_entry(closed, "A")["status"] == "Closed"
