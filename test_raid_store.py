"""Unit tests for raid_store.py: the backend-dispatch facade (Section 14).

Confirms the extension-based dispatch actually routes to the right
backend for every one of the four contract functions, and that the
seed-path defaulting picks the right seed for each backend.
"""

import json

import raid_store

TEMPLATE = "RAID-log-template.xlsx"


def json_seed(tmp_path, entries):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({"entries": entries}))
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
# is_xlsx / default_seed_path
# ---------------------------------------------------------------------------

def test_is_xlsx_true_for_xlsx_extension():
    assert raid_store.is_xlsx("anything.xlsx") is True
    assert raid_store.is_xlsx("ANYTHING.XLSX") is True


def test_is_xlsx_false_for_db_extension():
    assert raid_store.is_xlsx("raid_log.db") is False


def test_default_seed_path_picks_json_for_db_store():
    assert raid_store.default_seed_path("raid_log.db") == raid_store.DEFAULT_JSON_SEED


def test_default_seed_path_picks_xlsx_template_for_xlsx_store():
    assert raid_store.default_seed_path("my_log.xlsx") == raid_store.DEFAULT_XLSX_TEMPLATE


# ---------------------------------------------------------------------------
# Dispatch: .db path routes to raid_db, .xlsx path routes to raid_xlsx
# ---------------------------------------------------------------------------

def test_ensure_db_and_load_entries_dispatch_to_sqlite_for_db_path(tmp_path):
    seed = json_seed(tmp_path, [entry(id="J-1")])
    db_path = str(tmp_path / "test.db")

    raid_store.ensure_db(db_path, seed)
    entries = raid_store.load_entries(db_path)

    assert [e["id"] for e in entries] == ["J-1"]


def test_ensure_db_and_load_entries_dispatch_to_xlsx_for_xlsx_path(tmp_path):
    xlsx_path = str(tmp_path / "working_copy.xlsx")

    raid_store.ensure_db(xlsx_path, TEMPLATE)
    entries = raid_store.load_entries(xlsx_path)

    assert [e["id"] for e in entries] == ["R-001", "A-002", "I-003", "D-004"]


def test_update_fields_dispatches_correctly_for_both_backends(tmp_path):
    seed = json_seed(tmp_path, [entry(id="J-1", status="Not Started")])
    db_path = str(tmp_path / "test.db")
    raid_store.ensure_db(db_path, seed)
    raid_store.update_fields(db_path, "J-1", status="Escalated")
    [db_entry] = raid_store.load_entries(db_path)
    assert db_entry["status"] == "Escalated"

    xlsx_path = str(tmp_path / "working_copy.xlsx")
    raid_store.ensure_db(xlsx_path, TEMPLATE)
    raid_store.update_fields(xlsx_path, "R-001", status="Escalated")
    [r001] = [e for e in raid_store.load_entries(xlsx_path) if e["id"] == "R-001"]
    assert r001["status"] == "Escalated"


def test_reset_db_dispatches_correctly_for_both_backends(tmp_path):
    seed = json_seed(tmp_path, [entry(id="J-1", status="Not Started")])
    db_path = str(tmp_path / "test.db")
    raid_store.ensure_db(db_path, seed)
    raid_store.update_fields(db_path, "J-1", status="Escalated")
    raid_store.reset_db(db_path, seed)
    [db_entry] = raid_store.load_entries(db_path)
    assert db_entry["status"] == "Not Started"

    xlsx_path = str(tmp_path / "working_copy.xlsx")
    raid_store.ensure_db(xlsx_path, TEMPLATE)
    raid_store.update_fields(xlsx_path, "R-001", status="Escalated")
    raid_store.reset_db(xlsx_path, TEMPLATE)
    [r001] = [e for e in raid_store.load_entries(xlsx_path) if e["id"] == "R-001"]
    assert r001["status"] == "Monitoring"


def test_two_backends_at_different_paths_stay_fully_independent(tmp_path):
    seed = json_seed(tmp_path, [entry(id="J-1")])
    db_path = str(tmp_path / "test.db")
    xlsx_path = str(tmp_path / "working_copy.xlsx")

    raid_store.ensure_db(db_path, seed)
    raid_store.ensure_db(xlsx_path, TEMPLATE)

    db_ids = {e["id"] for e in raid_store.load_entries(db_path)}
    xlsx_ids = {e["id"] for e in raid_store.load_entries(xlsx_path)}
    assert db_ids == {"J-1"}
    assert xlsx_ids == {"R-001", "A-002", "I-003", "D-004"}
