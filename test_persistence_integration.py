"""Section 13.7 DoD: prove the idempotency guarantee holds across two
genuinely separate process invocations, not just two calls within one
Python process (which is all the other test files can prove, since they
call functions directly against a shared in-memory interpreter).

Each test here shells out to `raid_tool.py` via subprocess.run() twice
against the same tmp_path database, so the second run has no access to
anything the first run held in memory -- the only thing it can see is
whatever actually got written to raid_log.db.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent
RAID_TOOL = str(REPO_DIR / "raid_tool.py")


def make_seed(tmp_path, entries):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps({"entries": entries}))
    return str(path)


def entry(**overrides):
    base = {
        "id": "RAID-X",
        "category": "Risk",
        "description": "Something that needs attention.",
        "owner": "Test Owner",
        "probability": 5,
        "impact": 5,
        "mitigation_plan": "A plan.",
        "date_raised": "2026-01-01",
        "start_date": "2026-01-02",
        "status": "In Progress",
        "materialized": False,
        "dependency_links": [],
        "blocked_by": [],
        "target_date": "2026-06-01",
        "last_updated": "2026-01-01",
    }
    base.update(overrides)
    return base


def run(*args):
    result = subprocess.run(
        [sys.executable, RAID_TOOL, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout + result.stderr, result.returncode


def test_escalation_is_idempotent_across_separate_process_invocations(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X", date_raised="2026-01-01")])
    db = str(tmp_path / "raid.db")
    common = ["escalate", "--data", seed, "--db", db, "--today", "2026-08-14", "--score-band", "High", "--days-open", "1", "--log", str(tmp_path / "log.jsonl")]

    first_output, first_code = run(*common)
    assert first_code == 0
    assert "Escalated this run: 1 -> ['RAID-X']" in first_output

    second_output, second_code = run(*common)
    assert second_code == 0
    assert "Escalated this run: 0 -> []" in second_output


def test_materialize_conversion_is_idempotent_across_separate_process_invocations(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X", category="Risk", materialized=True, status="Monitoring")])
    db = str(tmp_path / "raid.db")
    common = ["materialize", "--data", seed, "--db", db]

    first_output, first_code = run(*common)
    assert first_code == 0
    assert "Materialized-Risk conversions this run: 1" in first_output
    assert "RAID-X: Risk -> Issue" in first_output

    second_output, second_code = run(*common)
    assert second_code == 0
    assert "Materialized-Risk conversions this run: 0" in second_output


def test_status_promotion_is_idempotent_across_separate_process_invocations(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X", status="Not Started", start_date="2026-02-01")])
    db = str(tmp_path / "raid.db")
    common = ["status", "--data", seed, "--db", db, "--today", "2026-08-14"]

    first_output, first_code = run(*common)
    assert first_code == 0
    assert "Status auto-promoted to In Progress: 1 -> ['RAID-X']" in first_output

    second_output, second_code = run(*common)
    assert second_code == 0
    assert "Status auto-promoted to In Progress: 0 -> []" in second_output


def test_close_persists_and_is_visible_to_a_separate_process(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X", status="In Progress")])
    db = str(tmp_path / "raid.db")

    close_output, close_code = run("retain", "--data", seed, "--db", db, "--close", "RAID-X")
    assert close_code == 0
    assert "RAID-X: Status set to Closed." in close_output
    assert "Total entries retained: 1 (Open: 0, Closed: 1)" in close_output

    # A brand new process, reading the same db, must see the close.
    query_output, query_code = run("retain", "--data", seed, "--db", db)
    assert query_code == 0
    assert "Total entries retained: 1 (Open: 0, Closed: 1)" in query_output


def test_removal_of_a_now_closed_entry_is_still_refused_by_a_separate_process(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X", status="In Progress")])
    db = str(tmp_path / "raid.db")

    run("retain", "--data", seed, "--db", db, "--close", "RAID-X")

    remove_output, remove_code = run("retain", "--data", seed, "--db", db, "--remove", "RAID-X")
    assert remove_code == 1
    assert "Refused" in remove_output
    assert "RAID-X" in remove_output


def test_state_is_shared_across_different_subcommands_not_just_the_same_one(tmp_path):
    # Escalate an entry, then confirm a completely different subcommand
    # (score) sees it as Escalated -- proving persistence is a shared
    # store, not something scoped to one command's own process.
    seed = make_seed(tmp_path, [entry(id="RAID-X", date_raised="2026-01-01")])
    db = str(tmp_path / "raid.db")

    run("escalate", "--data", seed, "--db", db, "--today", "2026-08-14", "--score-band", "High", "--days-open", "1", "--log", str(tmp_path / "log.jsonl"))

    score_output, score_code = run("score", "--data", seed, "--db", db)
    assert score_code == 0
    # score_and_validate doesn't print Status, but a subsequent `status`
    # run against the same db confirms the Escalated state stuck.
    status_output, status_code = run("status", "--data", seed, "--db", db, "--today", "2026-08-14")
    assert status_code == 0
    assert "Escalated" in status_output


# ---------------------------------------------------------------------------
# reset-db — US-10
# ---------------------------------------------------------------------------

def test_reset_db_discards_state_persisted_by_a_separate_earlier_process(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X", date_raised="2026-01-01")])
    db = str(tmp_path / "raid.db")

    escalate_output, escalate_code = run(
        "escalate", "--data", seed, "--db", db, "--today", "2026-08-14",
        "--score-band", "High", "--days-open", "1", "--log", str(tmp_path / "log.jsonl"),
    )
    assert escalate_code == 0
    assert "Escalated this run: 1" in escalate_output

    reset_output, reset_code = run("reset-db", "--data", seed, "--db", db)
    assert reset_code == 0
    assert "reset to the 1 entries" in reset_output

    status_output, status_code = run("status", "--data", seed, "--db", db, "--today", "2026-08-14")
    assert status_code == 0
    assert "Escalated" not in status_output
    assert "In Progress" in status_output  # back to its original, unescalated status


def test_reset_db_never_modifies_the_seed_json_file(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X")])
    original_content = Path(seed).read_text()
    db = str(tmp_path / "raid.db")

    run("escalate", "--data", seed, "--db", db, "--today", "2026-08-14", "--score-band", "Low", "--days-open", "0", "--log", str(tmp_path / "log.jsonl"))
    run("reset-db", "--data", seed, "--db", db)

    assert Path(seed).read_text() == original_content


def test_reset_db_is_not_an_error_when_the_db_does_not_exist_yet(tmp_path):
    seed = make_seed(tmp_path, [entry(id="RAID-X")])
    db = str(tmp_path / "brand_new.db")

    reset_output, reset_code = run("reset-db", "--data", seed, "--db", db)
    assert reset_code == 0
    assert "reset to the 1 entries" in reset_output
