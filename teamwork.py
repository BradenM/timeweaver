#!/usr/bin/env python3

"""TimeWarrior Teamwork Plugin

Plugin for TimeWarrior for integration with Teamwork.
Publishes any entries w/o a 'logged' tag, then tags them
as logged.

"""

import json
import subprocess as sp
import sys
from collections import namedtuple
from enum import Enum
from pathlib import Path

import dpath.util
import requests
from dateutil import parser as dateparser
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table, box

ROSS_ID = os.getenv('TEAMWORK_ID')

DATE_FORMAT = "%Y%m%d"
TIME_FORMAT = "%H:%M"


class Project(Enum):
    ARROYODEV = ***REMOVED***
    ***REMOVED*** = ***REMOVED***
    ***REMOVED*** = ***REMOVED***
    ***REMOVED*** = ***REMOVED***


class Task(Enum):
    ***REMOVED*** = ***REMOVED***
    ***REMOVED***_MEETING = ***REMOVED***
    ***REMOVED*** = ***REMOVED***


class Tag(Enum):
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"  # ***REMOVED***
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"
    ***REMOVED*** = "***REMOVED***"


EntryMeta = namedtuple("EntryMeta", ["project", "task", "tags"])

META_MAP = {
    "***REMOVED***": EntryMeta(Project.***REMOVED***.value, Task.***REMOVED***.value, []),
    "***REMOVED***": EntryMeta(Project.***REMOVED***.value, None, []),
    "***REMOVED***": {
        "GENERAL": EntryMeta(Project.ARROYODEV.value, Task.***REMOVED***_MEETING.value, [Tag.***REMOVED***.value])
    },
    "***REMOVED***": {
        "GENERAL": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value, Tag.***REMOVED***.value]),
        "API": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value, Tag.***REMOVED***.value]),
        "APP": EntryMeta(Project.***REMOVED***.value, None, [Tag.***REMOVED***.value, Tag.***REMOVED***.value, Tag.***REMOVED***.value])
    },
    "ARROYODEV": {
        "GENERAL": EntryMeta(Project.ARROYODEV.value, None, [])
    }
}


def parse_input():
    lines = sys.stdin.readlines()
    gap = lines.index("\n")
    config = lines[:gap]
    data = json.loads("".join(lines[gap:]))
    return config, data


def get_description(title, annotation):
    default_text = f"# {title}\n{annotation}"
    return default_text


def iter_meta_from_tags(tags):
    for i in range(len(tags)):
        meta_name = "_".join(tags[: len(tags) - i]).upper()
        if meta_name in META_MAP:
            yield META_MAP.get(meta_name)


def create_teamwork_entry(data):
    annotation = data.get("annotation", "no annotation found!")
    tags = ", ".join(data["tags"])
    desc = get_description(tags, annotation)
    meta = next(
        iter_meta_from_tags(data["tags"]), EntryMeta(Project.ARROYODEV.value, None, [])
    )
    start = dateparser.isoparse(data["start"]).astimezone()
    end = dateparser.isoparse(data["end"]).astimezone()
    delta = relativedelta(end, start)
    # add extra tags
    extra_tags = [Tag.__dict__.get(t.upper(), None) for t in data["tags"][1:]]
    meta.tags.extend([t.value for t in extra_tags if t is not None])
    base_uri = "***REMOVED***"
    endpoint = f"/projects/{meta.project}/time_entries.json"
    if meta.task:
        endpoint = f"/tasks/{meta.task}/time_entries.json"
    return {
        "endpoint": base_uri + endpoint,
        "entry-id": data.get("id", -1),
        "time-entry": {
            "description": desc,
            "person-id": str(USER_ID),
            "date": start.date().strftime(DATE_FORMAT),
            "time": start.time().strftime(TIME_FORMAT),
            "hours": str(delta.hours),
            "minutes": str(delta.minutes),
            "isbillable": False,
            "tags": ",".join((str(s) for s in meta.tags)),
        },
    }


def post_teamwork_entry(entry):
    endpoint = entry.pop("endpoint")
    entry_id = entry.pop("entry-id")
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)
    headers = {
        "Authorization": f"Basic {os.getenv('TEAMWORK_TOKEN')}"
    }
    resp = requests.post(endpoint, headers=headers, json=entry)
    resp.raise_for_status()
    tag_timew_entry(entry_id, "logged")


def tag_timew_entry(entry_id, tag):
    bin = "/usr/bin/timew"
    cmd = [bin, "tag", f"@{entry_id}", tag]
    print(f"Tagging entry @{entry_id} as logged!")
    sp.run(cmd).check_returncode()


_, data = parse_input()

unlogged_entries = [d for d in data if "logged" not in d["tags"]]
entries = [create_teamwork_entry(d) for d in unlogged_entries]

# pprint(entries)

table = Table(
    "Entry",
    "Date",
    "Time",
    "Description",
    title="Teamwork Entries",
    show_lines=True,
    box=box.HEAVY_EDGE,
)

totals = (0, 0)
for entry in reversed(entries):
    t_entry = entry["time-entry"]
    date = f'{t_entry["date"]} {t_entry["time"]}'
    time = ":".join((t_entry["hours"], t_entry["minutes"]))
    totals = (totals[0] + int(t_entry["hours"]), totals[1] + int(t_entry["minutes"]))
    table.add_row(str(entry["entry-id"]), date, time, t_entry["description"])
    post_teamwork_entry(entry)


con = Console(force_terminal=True, width=255)
con.print(table)

hours, minutes = totals
hours += minutes // 60  # Get extra hours from minutes
minutes = minutes % 60  # Get remainder minutes
con.print(f"\n[white][bold]Total Time:[/bold] {hours}hrs {minutes}mins[/white]\n")
