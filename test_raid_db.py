"""Unit tests for US-9's storage layer: raid_db.py."""

import json
from pathlib import Path

import raid_db


def seed_file(tmp_path, entries, name="seed.json"):
    data = {"entries": entries}
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return str(path)


def entry(**overrides):
    base = {
        "id": "RAID-X",
        "category": "Risk",
        "description": "Something risky.",
        "date_raised": "2026-01-01",
        "owner": "Test Owner",
        "probability": 3,
        "impact": 4,
        "mitigation_plan": "A plan.",
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


# ---------------------------------------------------------------------------
# ensure_db
# ---------------------------------------------------------------------------

def test_ensure_db_creates_and_seeds_from_json(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1")])
    db_path = str(tmp_path / "test.db")

    raid_db.ensure_db(db_path, seed)

    entries = raid_db.load_entries(db_path)
    assert [e["id"] for e in entries] == ["RAID-1"]


def test_ensure_db_is_a_no_op_if_db_already_exists(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    # Mutate the live DB, then call ensure_db again with a *different*
    # seed -- it must not re-seed and wipe out the mutation.
    raid_db.update_fields(db_path, "RAID-1", status="Closed")
    other_seed = seed_file(tmp_path, [entry(id="RAID-1"), entry(id="RAID-2")])
    raid_db.ensure_db(db_path, other_seed)

    entries = raid_db.load_entries(db_path)
    assert [e["id"] for e in entries] == ["RAID-1"]
    assert entries[0]["status"] == "Closed"


# ---------------------------------------------------------------------------
# load_entries — round-tripping
# ---------------------------------------------------------------------------

def test_load_entries_round_trips_scalar_fields(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", owner="Maria Chen", probability=4, impact=5)])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    [e] = raid_db.load_entries(db_path)
    assert e["owner"] == "Maria Chen"
    assert e["probability"] == 4
    assert e["impact"] == 5


def test_load_entries_round_trips_list_fields(tmp_path):
    seed = seed_file(
        tmp_path,
        [entry(id="RAID-1", dependency_links=["RAID-2"], blocked_by=["RAID-3", "RAID-4"])],
    )
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    [e] = raid_db.load_entries(db_path)
    assert e["dependency_links"] == ["RAID-2"]
    assert e["blocked_by"] == ["RAID-3", "RAID-4"]


def test_load_entries_round_trips_empty_list_fields(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", dependency_links=[], blocked_by=[])])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    [e] = raid_db.load_entries(db_path)
    assert e["dependency_links"] == []
    assert e["blocked_by"] == []


def test_load_entries_round_trips_materialized_true_false_and_none(tmp_path):
    seed = seed_file(
        tmp_path,
        [
            entry(id="R1", materialized=True),
            entry(id="R2", materialized=False),
            entry(id="R3", category="Issue", materialized=None),
        ],
    )
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    by_id = {e["id"]: e for e in raid_db.load_entries(db_path)}
    assert by_id["R1"]["materialized"] is True
    assert by_id["R2"]["materialized"] is False
    assert by_id["R3"]["materialized"] is None


def test_load_entries_returns_in_id_order(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-3"), entry(id="RAID-1"), entry(id="RAID-2")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    ids = [e["id"] for e in raid_db.load_entries(db_path)]
    assert ids == ["RAID-1", "RAID-2", "RAID-3"]


# ---------------------------------------------------------------------------
# update_fields
# ---------------------------------------------------------------------------

def test_update_fields_writes_a_single_field(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", status="Not Started")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    raid_db.update_fields(db_path, "RAID-1", status="In Progress")

    [e] = raid_db.load_entries(db_path)
    assert e["status"] == "In Progress"


def test_update_fields_writes_multiple_fields_at_once(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", category="Risk", status="Monitoring")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    raid_db.update_fields(db_path, "RAID-1", category="Issue", status="Escalated")

    [e] = raid_db.load_entries(db_path)
    assert e["category"] == "Issue"
    assert e["status"] == "Escalated"


def test_update_fields_leaves_other_fields_and_entries_untouched(tmp_path):
    seed = seed_file(
        tmp_path,
        [entry(id="RAID-1", owner="Maria Chen", status="Not Started"), entry(id="RAID-2", status="Not Started")],
    )
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    raid_db.update_fields(db_path, "RAID-1", status="Closed")

    by_id = {e["id"]: e for e in raid_db.load_entries(db_path)}
    assert by_id["RAID-1"]["owner"] == "Maria Chen"  # untouched field
    assert by_id["RAID-2"]["status"] == "Not Started"  # untouched entry


def test_update_fields_is_a_no_op_with_no_fields_given(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", status="Not Started")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    raid_db.update_fields(db_path, "RAID-1")

    [e] = raid_db.load_entries(db_path)
    assert e["status"] == "Not Started"


def test_update_fields_persists_across_separate_connections(tmp_path):
    # Simulates two separate process invocations sharing the same file:
    # each raid_db call opens and closes its own connection.
    seed = seed_file(tmp_path, [entry(id="RAID-1", status="Not Started")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    raid_db.update_fields(db_path, "RAID-1", status="Escalated")
    # A brand new load_entries call is a brand new sqlite3.connect().
    [e] = raid_db.load_entries(db_path)
    assert e["status"] == "Escalated"


# ---------------------------------------------------------------------------
# reset_db — US-10
# ---------------------------------------------------------------------------

def test_reset_db_discards_persisted_state(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", status="Not Started", category="Risk")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)
    raid_db.update_fields(db_path, "RAID-1", status="Escalated", category="Issue")

    raid_db.reset_db(db_path, seed)

    [e] = raid_db.load_entries(db_path)
    assert e["status"] == "Not Started"
    assert e["category"] == "Risk"


def test_reset_db_reflects_current_seed_content_not_a_stale_copy(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1")])
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)

    # Reseed from a *different* seed (simulates the mock dataset having
    # been edited between runs) -- reset_db must reflect it, unlike
    # ensure_db, which would silently no-op on an existing db.
    other_seed = seed_file(tmp_path, [entry(id="RAID-1"), entry(id="RAID-2")], name="seed2.json")
    raid_db.reset_db(db_path, other_seed)

    ids = {e["id"] for e in raid_db.load_entries(db_path)}
    assert ids == {"RAID-1", "RAID-2"}


def test_reset_db_when_db_does_not_exist_yet_behaves_like_a_fresh_seed(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1")])
    db_path = str(tmp_path / "does_not_exist_yet.db")

    raid_db.reset_db(db_path, seed)  # no prior ensure_db call

    entries = raid_db.load_entries(db_path)
    assert [e["id"] for e in entries] == ["RAID-1"]


def test_reset_db_never_writes_to_the_seed_file(tmp_path):
    seed = seed_file(tmp_path, [entry(id="RAID-1", status="Not Started")])
    original_content = Path(seed).read_text()
    db_path = str(tmp_path / "test.db")
    raid_db.ensure_db(db_path, seed)
    raid_db.update_fields(db_path, "RAID-1", status="Escalated")

    raid_db.reset_db(db_path, seed)

    assert Path(seed).read_text() == original_content
