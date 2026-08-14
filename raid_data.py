"""Shared data loading for the RAID Log Automator CLI scripts.

Every entry point loads the mock dataset and immediately applies the
US-5 Materialized-Risk -> Issue conversion, so a materialized Risk is
treated as an Issue consistently everywhere downstream (validation,
scoring, escalation, digest, Sprint Ready) -- not just when US-5's own
script happens to be the one that ran. Nothing persists back to the JSON
file (see the other modules' docstrings), so this conversion has to be
re-applied on every load rather than assumed to already be reflected in
the data on disk.
"""

import json

import materialize_conversion as mc


def load_dataset(path):
    with open(path) as f:
        return json.load(f)


def load_converted_entries(path):
    """Returns (dataset, converted_entries). `dataset` retains the raw
    entries (needed for self_check's known_test_cases lookups);
    converted_entries is what every other module's process()/build_*()
    functions should receive."""
    dataset = load_dataset(path)
    converted_entries, _ = mc.process(dataset["entries"])
    return dataset, converted_entries
