"""Tests for raid_data.load_converted_entries -- the shared, DB-backed
loader used by score_and_validate, digest, sprint_ready, escalation, and
retention (Section 13 / US-9).

Originally a regression test for the materialize-conversion chaining bug
(RAID-006 showing as "Risk" in every script except materialize_conversion.py
itself, since none of them applied the US-5 conversion before doing their
own work). Now also covers that both automatic transitions -- US-5
conversion and US-3 status promotion -- are applied *and persisted* to
the database, not just reflected in-memory for one call.
"""

import json

import raid_data
import raid_db


def entry(**overrides):
    base = {
        "id": "RAID-X",
        "category": "Risk",
        "materialized": False,
        "owner": "Test Owner",
        "mitigation_plan": "Some plan",
        "probability": 4,
        "impact": 4,
        "date_raised": "2026-01-01",
        "start_date": None,
        "status": "Not Started",
        "blocked_by": [],
        "dependency_links": [],
        "target_date": "2026-06-01",
        "last_updated": "2026-01-01",
    }
    base.update(overrides)
    return base


def write_seed(tmp_path, entries, name="data.json"):
    data_path = tmp_path / name
    data_path.write_text(json.dumps({"entries": entries}))
    return str(data_path)


def db_path_for(tmp_path, name="test.db"):
    return str(tmp_path / name)


def test_load_converted_entries_applies_materialize_conversion(tmp_path):
    seed = write_seed(tmp_path, [entry(id="RAID-X", materialized=True, status="Monitoring")])
    db = db_path_for(tmp_path)

    dataset, entries = raid_data.load_converted_entries(seed, db)

    assert entries[0]["category"] == "Issue"
    # The raw seed (used for self_check's known_test_cases lookups) keeps
    # the original, unconverted category -- it's never written to.
    assert dataset["entries"][0]["category"] == "Risk"


def test_load_converted_entries_leaves_non_materialized_entries_untouched(tmp_path):
    seed = write_seed(tmp_path, [entry(id="RAID-Y", materialized=False)])
    db = db_path_for(tmp_path)

    _, entries = raid_data.load_converted_entries(seed, db)
    assert entries[0]["category"] == "Risk"


def test_materialize_conversion_is_persisted_across_separate_calls(tmp_path):
    seed = write_seed(tmp_path, [entry(id="RAID-X", materialized=True, status="Monitoring")])
    db = db_path_for(tmp_path)

    raid_data.load_converted_entries(seed, db)

    # A second call reads whatever is now in the database -- it should
    # find Category already "Issue" without needing the JSON seed to
    # change or the conversion to "re-fire" in any observable way.
    stored = raid_db.load_entries(db)
    assert stored[0]["category"] == "Issue"

    _, entries = raid_data.load_converted_entries(seed, db)
    assert entries[0]["category"] == "Issue"


def test_status_promotion_is_applied_and_persisted(tmp_path):
    seed = write_seed(tmp_path, [entry(id="RAID-Z", status="Not Started", start_date="2026-02-01")])
    db = db_path_for(tmp_path)

    _, entries = raid_data.load_converted_entries(seed, db)
    assert entries[0]["status"] == "In Progress"

    stored = raid_db.load_entries(db)
    assert stored[0]["status"] == "In Progress"


def test_two_independent_dbs_from_the_same_seed_stay_independent(tmp_path):
    # Regression guard for the original bug in this test file: two calls
    # must not silently share state through a default/relative db path.
    seed = write_seed(tmp_path, [entry(id="RAID-A", materialized=True, status="Monitoring")])
    db1 = db_path_for(tmp_path, "one.db")
    db2 = db_path_for(tmp_path, "two.db")

    _, entries1 = raid_data.load_converted_entries(seed, db1)
    _, entries2 = raid_data.load_converted_entries(seed, db2)

    assert entries1[0]["category"] == "Issue"
    assert entries2[0]["category"] == "Issue"
    assert raid_db.load_entries(db1)[0]["id"] == "RAID-A"
    assert raid_db.load_entries(db2)[0]["id"] == "RAID-A"
