"""Shared data loading for the RAID Log Automator CLI scripts.

Per Section 13 (US-9), the live working store is a local SQLite database
(raid_log.db by default), auto-created and seeded from raid_mock_data.json
the first time it's needed. Per Section 14 (US-11), the store can instead
be an xlsx workbook -- raid_store.py picks the backend by file extension,
so nothing here needs to know or care which one is active. Either way the
seed file itself is never written to -- it stays the canonical, portable
example dataset.

Every entry point using load_converted_entries() gets entries with the
two automatic, rule-based transitions already applied *and persisted*:
the US-5 Materialized-Risk -> Issue conversion and the US-3 Not
Started -> In Progress promotion. Neither is a PM judgment call -- both
fire the moment their trigger condition is true -- so this loader treats
them as part of "what's currently true," the same way v1 did in-memory,
just now durable across separate process invocations too. (On the xlsx
backend, the US-3 promotion never actually fires, since there's no Start
Date column to trigger it -- see Section 14.3.)

This is the "give me current truth" convenience layer for read-only
callers (scoring, digest, Sprint Ready) and for callers with their own
additional explicit persistence (escalation, retention). Callers that
need to *report* what changed in this specific run (materialize_conversion.py,
days_and_status.py) do their own direct, lower-level sequence instead --
see their own load_and_convert()/load_and_process() -- since by the time
this loader returns, any transition it found has already been folded in
and looks identical to one that happened in some earlier run.
"""

import json

import days_and_status as ds
import materialize_conversion as mc
import raid_store


def load_dataset(path):
    """Returns the raw seed as a dict for self_check's known_test_cases
    lookups. Only the JSON seed has `_schema_notes` at all -- an xlsx
    seed returns {}, which every self_check already treats as "nothing
    to check" and no-ops on."""
    if raid_store.is_xlsx(path):
        return {}
    with open(path) as f:
        return json.load(f)


def load_converted_entries(seed_path, db_path=raid_store.DEFAULT_DB_PATH):
    """Returns (dataset, entries). `dataset` is the raw seed (used for
    self_check's known_test_cases lookups); `entries` is read from the
    persistent store with both automatic transitions applied and
    persisted."""
    raid_store.ensure_db(db_path, seed_path)
    dataset = load_dataset(seed_path)
    entries = raid_store.load_entries(db_path)

    converted, conversion_events = mc.process(entries)
    mc.persist_conversions(db_path, conversion_events)

    status_results = ds.process(converted)
    ds.persist_status_promotions(db_path, status_results)
    promoted_status = {r["id"]: r["status"] for r in status_results if r["status_changed"]}
    live_entries = [dict(e, status=promoted_status.get(e["id"], e["status"])) for e in converted]

    return dataset, live_entries
