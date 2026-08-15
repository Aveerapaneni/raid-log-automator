#!/usr/bin/env python3
"""RAID Log Automator — single CLI entry point.

Wraps the ten user-story modules (US-1 through US-10) as subcommands of
one command, per Section 12's Definition of Done ("script runs end-to-end
against the independent mock dataset"). Each subcommand is a thin
dispatch to that story's own module -- the logic lives there; this file
only wires up shared options (--data, --db, --today) and routing.

Per Section 13 (US-9), state lives in a local SQLite database
(raid_log.db by default), auto-created and seeded from raid_mock_data.json
on first use. raid_mock_data.json itself is never written to.

Run `python3 raid_tool.py <subcommand> --help` for a given subcommand's
own options. `report` runs the full end-to-end picture in one command;
`escalate` is deliberately left out of `report` since it requires a
PM-supplied threshold every time (US-4) rather than something safe to
run unattended.
"""

import argparse
import sys
from datetime import datetime, timezone

import days_and_status as ds
import digest as dg
import escalation as esc
import materialize_conversion as mc
import raid_data
import raid_db
import retention as rt
import score_and_validate as sv
import sprint_ready as sr


def add_common_args(parser, today=True):
    parser.add_argument("--data", default="raid_mock_data.json", help="Path to the mock RAID dataset JSON")
    parser.add_argument("--db", default=raid_db.DEFAULT_DB_PATH, help="Path to the persistent SQLite store")
    if today:
        parser.add_argument("--today", default=None, help="Override 'today' as YYYY-MM-DD")


def resolve_today(args):
    return ds.parse_date(args.today) if getattr(args, "today", None) else None


def cmd_score(args):
    dataset, entries = raid_data.load_converted_entries(args.data, args.db)
    results = sv.process(entries)
    sv.print_report(results)
    sv.self_check(dataset, results)
    return 0


def cmd_status(args):
    dataset, results = ds.load_and_process(args.db, args.data, today=resolve_today(args))
    ds.print_report(results)
    ds.self_check(dataset, results)
    return 0


def cmd_escalate(args):
    try:
        score_band = esc.resolve_score_band(args.score_band)
        days_open_threshold = esc.resolve_days_open_threshold(args.days_open)
    except ValueError as exc:
        print(f"Refusing to run escalation check: {exc}", file=sys.stderr)
        return 1

    dataset, entries = raid_data.load_converted_entries(args.data, args.db)
    records = esc.build_records(entries, today=resolve_today(args))
    timestamp = datetime.now(timezone.utc).isoformat()
    updated_records, events = esc.apply_escalations(records, score_band, days_open_threshold, timestamp=timestamp)

    esc.print_report(records, events, score_band, days_open_threshold)
    esc.persist_escalations(args.db, events)
    esc.append_log(events, args.log_path)
    if events:
        print(f"\nLogged {len(events)} escalation(s) to {args.log_path}")
    return 0


def cmd_materialize(args):
    dataset, updated, events = mc.load_and_convert(args.db, args.data)
    mc.print_report(events)
    mc.self_check(dataset, updated, events)
    return 0


def cmd_digest(args):
    dataset, entries = raid_data.load_converted_entries(args.data, args.db)
    items = dg.select_top_items(entries, count=args.count, today=resolve_today(args))
    label = args.today or "today"
    print(dg.format_digest(items, label))
    dg.self_check(dataset, items)
    return 0


def cmd_sprint_ready(args):
    dataset, entries = raid_data.load_converted_entries(args.data, args.db)
    pile = sr.build_pile(entries, today=resolve_today(args))
    sr.print_report(pile)
    sr.self_check(dataset, pile)
    return 0


def cmd_reset_db(args):
    raid_db.reset_db(args.db, args.data)
    entries = raid_db.load_entries(args.db)
    print(f"{args.db}: reset to the {len(entries)} entries in {args.data}.")
    print("All persisted state (Status/Category/Materialized changes) has been discarded.")
    return 0


def cmd_retain(args):
    dataset, entries = raid_data.load_converted_entries(args.data, args.db)

    if args.close:
        try:
            entries = rt.close_entry(entries, args.close)
            raid_db.update_fields(args.db, args.close, status=rt.CLOSED)
            print(f"{args.close}: Status set to Closed.")
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    exit_code = 0
    if args.remove:
        try:
            rt.remove_entry(entries, args.remove)
        except rt.RetentionError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            exit_code = 1
        except KeyError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    all_count = len(rt.list_entries(entries))
    open_count = len(rt.list_entries(entries, include_closed=False))
    print(f"Total entries retained: {all_count} (Open: {open_count}, Closed: {all_count - open_count})")
    rt.self_check(dataset, entries)
    return exit_code


def cmd_report(args):
    """The full end-to-end picture in one command (Section 12 DoD)."""
    today = resolve_today(args)

    def header(title):
        print()
        print("#" * 70)
        print(f"# {title}")
        print("#" * 70)

    header("1. Materialized-Risk conversion (US-5)")
    _, _, mc_events = mc.load_and_convert(args.db, args.data)
    mc.print_report(mc_events)

    header("2. Priority scoring & validation (US-1 / US-2)")
    dataset, entries = raid_data.load_converted_entries(args.data, args.db)
    score_results = sv.process(entries)
    sv.print_report(score_results)

    header("3. Days Open & Status (US-3)")
    _, status_results = ds.load_and_process(args.db, args.data, today=today)
    ds.print_report(status_results)

    header("4. Sprint Ready pile (US-8)")
    _, entries = raid_data.load_converted_entries(args.data, args.db)
    sr.print_report(sr.build_pile(entries, today=today))

    header(f"5. Digest — top {args.count} items (US-6)")
    items = dg.select_top_items(entries, count=args.count, today=today)
    print(dg.format_digest(items, args.today or "today"))

    print()
    print("Note: 'escalate' is intentionally not included above -- US-4 requires a")
    print("PM-supplied score-band and days-open threshold every run, rather than a")
    print("value safe to bake into an unattended report. Run it separately:")
    print("  python3 raid_tool.py escalate --score-band <Low|Medium|High> --days-open <N>")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="raid_tool.py",
        description="RAID Log Automator — one CLI for all user stories.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("score", help="US-1/US-2: priority scoring and validation")
    add_common_args(p, today=False)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("status", help="US-3: Days Open and Status auto-transition")
    add_common_args(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("escalate", help="US-4: runtime-configurable escalation check")
    add_common_args(p)
    p.add_argument("--score-band", dest="score_band", default=None, choices=list(esc.PRIORITY_RANK))
    p.add_argument("--days-open", dest="days_open", default=None, type=int)
    p.add_argument("--log", dest="log_path", default="escalation_log.jsonl")
    p.set_defaults(func=cmd_escalate)

    p = sub.add_parser("materialize", help="US-5: convert materialized Risks to Issues")
    add_common_args(p, today=False)
    p.set_defaults(func=cmd_materialize)

    p = sub.add_parser("digest", help="US-6: manually-triggered top 3-5 digest")
    add_common_args(p)
    p.add_argument("--count", type=int, default=5, choices=[3, 4, 5])
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("retain", help="US-7: close/attempt-remove and query entries")
    add_common_args(p, today=False)
    p.add_argument("--close", metavar="ID", help="Set an entry's Status to Closed (persisted)")
    p.add_argument("--remove", metavar="ID", help="Attempt to remove an entry — always refused")
    p.set_defaults(func=cmd_retain)

    p = sub.add_parser("sprint-ready", help="US-8: build the Sprint Ready pile")
    add_common_args(p)
    p.set_defaults(func=cmd_sprint_ready)

    p = sub.add_parser("reset-db", help="US-10: discard persisted state and reseed from the mock dataset")
    add_common_args(p, today=False)
    p.set_defaults(func=cmd_reset_db)

    p = sub.add_parser("report", help="Run the full end-to-end picture in one command")
    add_common_args(p)
    p.add_argument("--count", type=int, default=5, choices=[3, 4, 5], help="Digest size within the report")
    p.set_defaults(func=cmd_report)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
