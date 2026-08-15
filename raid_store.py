"""Storage backend facade for the RAID Log Automator (PRD Section 14).

Dispatches to raid_db.py (SQLite, .db) or raid_xlsx.py (Excel, .xlsx)
based on the target path's extension, so raid_data.py and every other
module can call one interface -- ensure_db/load_entries/update_fields/
reset_db -- without knowing or caring which backend is active.
"""

import raid_db
import raid_xlsx

DEFAULT_DB_PATH = raid_db.DEFAULT_DB_PATH
DEFAULT_XLSX_TEMPLATE = "RAID-log-template.xlsx"
DEFAULT_JSON_SEED = "raid_mock_data.json"


def is_xlsx(path):
    return str(path).lower().endswith(".xlsx")


def _backend_for(path):
    return raid_xlsx if is_xlsx(path) else raid_db


def default_seed_path(db_path):
    """The seed a given store path should be auto-created from, when
    the PM didn't explicitly supply one -- the mock JSON dataset for a
    .db store, the xlsx template for a .xlsx store (Section 14.4)."""
    return DEFAULT_XLSX_TEMPLATE if is_xlsx(db_path) else DEFAULT_JSON_SEED


def ensure_db(db_path, seed_path):
    return _backend_for(db_path).ensure_db(db_path, seed_path)


def load_entries(db_path):
    return _backend_for(db_path).load_entries(db_path)


def update_fields(db_path, entry_id, **fields):
    return _backend_for(db_path).update_fields(db_path, entry_id, **fields)


def reset_db(db_path, seed_path):
    return _backend_for(db_path).reset_db(db_path, seed_path)
