"""Regression test for the materialize-conversion chaining bug: every
module's main() must see a materialized Risk as an Issue, not just
materialize_conversion.py itself. Caught while building the unified CLI
-- RAID-006 (materialized) was showing as "Risk" in score_and_validate,
days_and_status, escalation, digest, and sprint_ready, because none of
them applied the US-5 conversion before doing their own work.
"""

import json

import raid_data


def test_load_converted_entries_applies_materialize_conversion(tmp_path):
    data = {
        "entries": [
            {
                "id": "RAID-X",
                "category": "Risk",
                "materialized": True,
                "owner": "Test Owner",
                "mitigation_plan": "Some plan",
                "probability": 4,
                "impact": 4,
                "date_raised": "2026-01-01",
                "start_date": None,
                "status": "Monitoring",
                "blocked_by": [],
                "dependency_links": [],
            }
        ]
    }
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps(data))

    dataset, entries = raid_data.load_converted_entries(str(data_path))

    assert entries[0]["category"] == "Issue"
    # The raw dataset (used for self_check's known_test_cases lookups)
    # keeps the original, unconverted category.
    assert dataset["entries"][0]["category"] == "Risk"


def test_load_converted_entries_leaves_non_materialized_entries_untouched(tmp_path):
    data = {
        "entries": [
            {
                "id": "RAID-Y",
                "category": "Risk",
                "materialized": False,
                "owner": "Test Owner",
                "mitigation_plan": "Some plan",
                "probability": 3,
                "impact": 3,
                "date_raised": "2026-01-01",
                "start_date": None,
                "status": "Not Started",
                "blocked_by": [],
                "dependency_links": [],
            }
        ]
    }
    data_path = tmp_path / "data.json"
    data_path.write_text(json.dumps(data))

    _, entries = raid_data.load_converted_entries(str(data_path))
    assert entries[0]["category"] == "Risk"
